"""Atomic completed-stage checkpoints survive failure in a later stage."""
import json
from pathlib import Path
from core.warm_start.job import atomic_json, write_summary
from core.mesh_issues import annotate, finding


def checkpoint(spec, result, kind, update_type):
    if result is None:
        return
    result = _diagnose(spec, result, kind, update_type)
    from core.draft_skin.protocol import write_result as write_skin
    from core.topology.protocol import write_result as write_topology
    from core.draft_skin.status import check_cancelled
    check_cancelled(lambda: Path(spec.cancel_path).exists())
    result.statistics["diagnostic_path"] = spec.log_path if hasattr(spec, "log_path") else spec.job_dir
    path = spec.skin_result_path if kind == "skin" else spec.topology_result_path
    (write_skin if kind == "skin" else write_topology)(path, annotate(result, kind))
    payload = read(spec)
    payload[kind] = dict(path=path, update_type=update_type, issues=result.statistics.get("issues", []))
    atomic_json(Path(spec.job_dir) / "completed_stages.json", payload)


def read(spec):
    path = Path(spec.job_dir) / "completed_stages.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def failed_stage(spec, error):
    if Path(spec.cancel_path).exists():
        return False
    completed = read(spec)
    if "skin" not in completed:
        return False
    issue = finding("TOPOLOGY_STAGE_FAILED", str(error), "topology", {"completed": list(completed)})
    summary = dict(state="PARTIAL", has_skin_result=True, has_topology_result="topology" in completed,
                   skin_update=completed["skin"]["update_type"], topology_update="stale",
                   update_type="partial", elapsed_seconds=0, issues=[issue], fallback_diagnostic=str(error))
    write_summary(spec.summary_path, summary)
    return True


def _diagnose(spec, result, kind, update_type):
    from core.mesh_diagnostics import check_result
    if kind == "skin" and update_type == "warm":
        return check_result(result, lambda: Path(spec.cancel_path).exists())
    return result
