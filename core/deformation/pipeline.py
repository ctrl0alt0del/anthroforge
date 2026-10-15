"""Draft-independent branch of the common strategy validation/result pipeline."""
from dataclasses import replace
import numpy as np
from .validation import validate_mesh_identity
from ..topology.validation import validate_topology
from ..mesh_diagnostics import check_result


def solve_final(context, options, strategy):
    from ..warm_start.strategy_pipeline import snapshot, array_bytes, _check_cancelled
    if options.failure_policy != "STOP":
        raise ValueError("Final-skin deformation requires STOP failure policy; rebuilding is forbidden.")
    if context.memory_budget and array_bytes(context, set()) > context.memory_budget:
        raise MemoryError("Final-skin deformation inputs exceed the worker memory budget.")
    reference = context.deformation_reference; old = context.topology
    validate_mesh_identity(reference, old.vertices, old.quads, reference.arrays["vertex_ids"])
    if context.contact_projection is None:
        raise ValueError("Shared final-skin contact preparation is unavailable; previous output retained.")
    candidate = strategy.solve(snapshot(replace(context, settings=options.settings)))
    _check_cancelled(context)
    candidate = context.contact_projection(context, candidate)
    validate_mesh_identity(reference, candidate.vertices, old.quads, candidate.vertex_ids)
    return quality(context,check_result(make_result(context,candidate),context.cancelled))


def quality(context, result):
    from .anatomy_quality import annotate
    baseline = reference_quality(context)
    result.statistics["reference_quality"] = baseline
    before = set(map(tuple,baseline.get("intersection_witnesses",())))
    after = set(map(tuple,result.statistics.get("intersection_witnesses",())))
    result.statistics["crossing_comparison"] = dict(inherited_witnesses=len(before & after),new_witnesses=len(after-before),
        complete=baseline.get("self_intersections",-1)==len(before) and result.statistics.get("self_intersections",-1)==len(after))
    return annotate(context,result)


def reference_quality(context):
    from ..mesh_diagnostics import intersections
    a = context.deformation_reference.arrays; prepared = context.prepared_solver
    baseline = getattr(prepared,"reference_quality",None)
    if baseline is None:
        faces = np.concatenate((a["quads"][:,[0,1,2]],a["quads"][:,[0,2,3]]))
        try: baseline = intersections(a["vertices"],faces,context.cancelled)
        except (RuntimeError,MemoryError,OSError) as error: baseline = dict(incomplete=str(error))
        if prepared is not None: prepared.reference_quality = baseline
    return baseline


def make_result(context, candidate):
    reference = context.deformation_reference; stats = dict(context.topology.statistics)
    stats.pop("issues", None); stats.pop("skin_structural_signature", None)
    for key in ("fidelity_ok","fidelity_p95","boundary_match","symmetry_error","symmetry_ok"):
        stats.pop(key,None)
    stats.update(last_update_type="deformed", deformation_reference=reference.signature,
        strategy_diagnostics=candidate.diagnostics, strategy_metrics={}, warnings=[])
    minimum = candidate.diagnostics.get("minimum_proxy_j", 1)
    if minimum <= 0: stats["warnings"].append(f"Deformation proxy has inverted elements (minimum J={minimum:.6g}).")
    append_warnings(stats,candidate)
    symmetry = candidate.diagnostics.get("contact",{}).get("symmetry_error",0.)
    stats.update(symmetry_error=symmetry,symmetry_ok=symmetry<=1e-7*max(float(np.ptp(candidate.vertices,axis=0).max()),1e-12))
    return replace(context.topology, vertices=np.asarray(candidate.vertices).copy(), statistics=stats,
        validation=validate_topology(candidate.vertices,context.topology.quads,stats),skin_binding=None,guide_binding=None)


def append_warnings(stats, candidate):
    if candidate.message: stats["warnings"].append(candidate.message)
    if candidate.diagnostics.get("iteration_limit_reached"):
        stats["warnings"].append("FAST reached its iteration limit; the finite proposal is published with incomplete convergence.")
    outside = candidate.diagnostics.get("outside_embeddings",0)
    if outside: stats["warnings"].append(f"Reference proxy extrapolates {outside} final-skin/anatomy sample embeddings outside its boundary.")
