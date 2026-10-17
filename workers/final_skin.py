"""Array-only final-skin jobs run inside the maintained persistent worker service."""
from pathlib import Path
import time
import numpy as np
from core.deformation.cache import SolverCache
from core.deformation.serialization import decode
from core.deformation.contact import project
from core.topology.protocol import read_result, write_result
from core.warm_start.job import read_job, write_summary, write_status
from core.warm_start.model import WarmUpdateStatus
from core.warm_start.strategy_model import TopologyUpdateContext, TopologyUpdateOptions
from core.warm_start.strategy_pipeline import run_topology_strategy

CACHE = SolverCache()


def run_final_job(folder):
    started = time.perf_counter(); spec = read_job(Path(folder)/"job.json")
    reference = decode(Path(folder,"reference.txt").read_text(encoding="ascii"))
    topology = read_result(spec.current_topology_path)
    with np.load(Path(folder,"targets.npz"),allow_pickle=False) as archive: targets = archive["targets"]
    options = TopologyUpdateOptions(**spec.topology_update)
    write_status(spec.status_path,WarmUpdateStatus(True,"Preparing deformation",.1,state="RUNNING"))
    prepared = CACHE.acquire(reference,options.strategy,options.settings,spec.cancel_path)
    context = TopologyUpdateContext(topology,None,None,None,"deformed",deformation_reference=reference,
        anatomy_targets=targets,cancel_path=spec.cancel_path,contact_projection=lambda c,r:contact_stage(spec,c,r),prepared_solver=prepared,
        memory_budget=2**30,cancelled=lambda:Path(spec.cancel_path).exists())
    write_status(spec.status_path,WarmUpdateStatus(True,"Solving and validating",.4,state="RUNNING"))
    outcome = run_topology_strategy(context,options)
    if outcome.result is None: raise RuntimeError(outcome.diagnostics["message"])
    finish(spec,outcome.result,reference.signature,time.perf_counter()-started)


def contact_stage(spec, context, candidate):
    np.savez(Path(spec.job_dir,"before_contact.npz"),vertices=candidate.vertices,quads=context.topology.quads,
        sample_prediction=context.prepared_solver.last_prediction)
    return project(context,candidate)


def finish(spec, result, signature, elapsed):
    from core.draft_skin.resources import memory_metrics
    if Path(spec.cancel_path).exists(): raise RuntimeError("CANCELLED")
    result.statistics.update(memory_metrics())
    write_result(spec.topology_result_path,result)
    summary = dict(state="SUCCEEDED",has_skin_result=False,has_topology_result=True,
        update_type="deformed",reference_signature=signature,elapsed_seconds=elapsed,
        issues=result.statistics.get("issues",[]))
    write_summary(spec.summary_path,summary)
    write_status(spec.status_path,WarmUpdateStatus(True,"Complete",1.,state="SUCCEEDED"))
