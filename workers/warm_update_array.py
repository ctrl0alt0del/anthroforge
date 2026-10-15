import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from core.warm_start.invalidation import WarmChangeClass, WarmChangeDecision
from core.warm_start.job import read_job, write_status, write_summary
from core.warm_start.model import SkinWarmCapture, WarmUpdateStatus
from core.warm_start.strategy_guides import guide_sets as _guide_sets
from workers.topology_update import attempt_update, augment_summary, preflight, annotate_rebuild

_TIMINGS = {}


def run_array_job(job_dir):
    _TIMINGS.clear()
    started, spec = time.perf_counter(), read_job(Path(job_dir) / "job.json")
    request = _request(spec)
    skin_capture, topology_capture, old_skin, old_topology = _timed("decode", _read_inputs, spec)
    decision = _decision(request)
    skin, skin_type = _timed("skin_stage", _solve_skin, spec, skin_capture, old_skin, decision)
    from workers.stage_results import checkpoint
    checkpoint(spec, skin, "skin", skin_type)
    active_skin = skin or old_skin
    topology, topology_type = _timed("topology_stage", _solve_topology, spec, topology_capture,
                                     active_skin, old_topology, decision, skin_type, _bound_skin(spec, old_skin), skin_capture.sources)
    _complete_stages(spec,request,skin_type,topology_type,started,skin,topology,active_skin,topology_capture)


def _complete_stages(spec, request, skin_type, topology_type, started, skin, topology, active_skin, topology_capture):
    from workers.stage_results import checkpoint
    _check_cancelled(spec)
    from workers.deformation_rebuild import prepare
    if topology is not None: prepare(spec,topology,active_skin,topology_capture)
    checkpoint(spec, topology, "topology", topology_type)
    _finish_job(spec, request, skin_type, topology_type, started, skin, topology)


def _finish_job(spec, request, skin_type, topology_type, started, skin, topology):
    summary = augment_summary(spec, _summary(request, skin_type, topology_type, started, skin, topology))
    write_summary(spec.summary_path, summary)
    _status(spec, "SUCCEEDED", "Complete", 1.0, _message(summary), summary["update_type"])


def _read_inputs(spec):
    from core.draft_skin.protocol import read_capture as read_skin_capture, read_result as read_skin
    from core.topology.protocol import read_capture as read_topology_capture, read_result as read_topology
    skin = read_skin_capture(spec.skin_capture_path)
    topology = read_topology_capture(spec.topology_capture_path) if Path(spec.topology_capture_path).exists() else None
    old_skin = read_skin(spec.current_skin_path) if Path(spec.current_skin_path).exists() else None
    old_topology = read_topology(spec.current_topology_path) if Path(spec.current_topology_path).exists() else None
    return skin, topology, old_skin, old_topology


def _decision(payload):
    kind = WarmChangeClass(payload["classification"])
    return WarmChangeDecision(kind, tuple(payload.get("reasons", ())),
                              bool(payload["skin_rebuild"]), bool(payload["topology_rebuild"]))


def _solve_skin(spec, capture, old, decision):
    if spec.mode == "FORCE_TOPOLOGY" and not decision.skin_rebuild:
        return None, "retained"
    if old is not None and not decision.skin_rebuild:
        warm = _warm_skin(capture, old, spec)
        if warm is not None:
            return warm, "warm"
    _status(spec, "RUNNING", "Skin rebuild", 0.22, "Rebuilding draft skin.")
    from core.draft_skin.solver import solve_capture
    result = solve_capture(capture, _skin_progress(spec), lambda: _cancelled(spec))
    result.statistics["last_update_type"] = "rebuilt"
    return result, "rebuilt"


def _warm_skin(capture, old, spec=None):
    from core.warm_start.skin_solver import solve_warm_skin
    warm_capture = _warm_capture(capture, old)
    started = time.perf_counter(); result = solve_warm_skin(warm_capture)
    if not result.status.valid:
        return None
    return _skin_result(capture, old, result, time.perf_counter() - started, spec)


def _warm_capture(capture, old):
    from core.warm_start.signatures import geometry_state_hash, solver_settings_hash, structural_signature
    stats = old.statistics
    return SkinWarmCapture(old.vertices, old.triangles, old.binding, (), capture.sources,
                           structural_signature(len(old.vertices), old.triangles),
                           stats.get("source_connectivity_signature", ""),
                           geometry_state_hash(capture.sources), solver_settings_hash(capture.settings),
                           stats.get("source_identity_signature", ""),
                           stats.get("source_connectivity_signature", ""),
                           stats.get("source_identity_signature", ""),
                           stats.get("structural_signature", ""), stats.get("solver_settings_hash", ""))


def _skin_result(capture, old, warm, elapsed, spec=None):
    from core.draft_skin.model import SkinResult
    from core.diagnostic_checks import warm_quality as revalidate
    stats = _skin_stats(capture, old.statistics, elapsed)
    validation, quality = revalidate(capture, warm.vertices, old.triangles,
        _skin_progress(spec) if spec else None, (lambda: _cancelled(spec)) if spec else None)
    stats.update(quality)
    return SkinResult(warm.vertices, old.triangles, old.collagen, stats, validation, warm.binding)


def _skin_stats(capture, previous, elapsed):
    from core.warm_start.invalidation import source_contact_signature
    from core.warm_start.signatures import geometry_state_hash, source_connectivity_signature, source_identity_signature
    stats = dict(previous)
    stats.update(source_identity_signature=source_identity_signature(capture.sources),
                 source_connectivity_signature=source_connectivity_signature(capture.sources),
                 source_contact_signature=source_contact_signature(capture.sources),
                 geometry_state_hash=geometry_state_hash(capture.sources), last_update_type="warm",
                 update_elapsed_seconds=float(elapsed))
    from core.warm_start.arap import arap_cache_stats
    stats["arap_cache"] = arap_cache_stats()
    return stats


def _solve_topology(spec, capture, skin, old, decision, skin_type, before_skin=None, sources=()):
    if capture is None or skin is None:
        from workers.topology_update import options_for
        from core.warm_start.strategy_pipeline import require_rebuild_allowed
        require_rebuild_allowed(options_for(spec))
        return None, "missing"
    from adapters.topology.strategy import binding_update_type
    skin_type = binding_update_type(before_skin, skin, skin_type)
    capture = _skin_capture(capture, skin)
    warm = attempt_update(spec, capture, skin, old, decision, skin_type, before_skin, sources)
    if warm is not None:
        return warm, "rebound" if skin_type == "rebuilt" else "warm"
    _status(spec, "RUNNING", "Topology rebuild", 0.64, "Rebuilding guided quad topology.")
    return _full_topology(spec, capture), "rebuilt"


def _skin_capture(capture, skin):
    vertices = np.asarray(skin.vertices, dtype=np.float64)
    return replace(capture, vertices=vertices, triangles=np.asarray(skin.triangles),
                   lower=vertices.min(axis=0), upper=vertices.max(axis=0))



def _full_topology(spec, capture):
    from adapters.topology.solver import solve_capture
    from adapters.topology.vendor import ensure_worker_dependencies
    result = solve_capture(capture, ensure_worker_dependencies(), _topology_progress(spec),
                           lambda: _cancelled(spec))
    result.statistics["last_update_type"] = "rebuilt"
    return annotate_rebuild(spec, result)


def _write_outputs(spec, skin, topology):
    if skin is not None:
        from core.draft_skin.protocol import write_result
        write_result(spec.skin_result_path, skin)
    if topology is not None:
        from core.topology.protocol import write_result
        write_result(spec.topology_result_path, topology)


def _summary(request, skin_type, topology_type, started, skin, topology):
    values = {skin_type, topology_type}
    update = "rebuilt" if "rebuilt" in values else ("rebound" if "rebound" in values else "warm")
    timings = dict(request.get("client_timings", {})); timings.update(_TIMINGS)
    timings["worker_total"] = time.perf_counter() - started
    return {"classification": request["classification"], "reasons": request.get("reasons", []),
            "skin_update": skin_type, "topology_update": topology_type, "update_type": update,
            "elapsed_seconds": _elapsed(timings), "timings": timings,
            "has_skin_result": skin is not None, "has_topology_result": topology is not None,
            "fallback_diagnostic": ""}


def _message(summary):
    return f"Update {summary['update_type']} in {summary['elapsed_seconds']:.2f}s ({summary['classification']})."


def _status(spec, state, stage, progress, message, update_type=""):
    write_status(spec.status_path, WarmUpdateStatus(state != "FAILED", stage, progress,
                 message, state=state, update_type=update_type))


def _skin_progress(spec):
    return lambda stage, value, message="": _status(spec, "RUNNING", stage, 0.22 + 0.32 * value, message)


def _topology_progress(spec):
    return lambda stage, value, message="": _status(spec, "RUNNING", stage, 0.64 + 0.32 * value, message)


def _cancelled(spec):
    return Path(spec.cancel_path).exists()


def _timed(name, function, *args):
    started = time.perf_counter(); result = function(*args)
    _TIMINGS[str(name)] = time.perf_counter() - started
    return result


def _elapsed(timings):
    client = sum(float(timings.get(name, 0.0)) for name in
                 ("bake", "skin_capture", "topology_capture", "serialization"))
    return client + float(timings.get("queue_wait", 0.0)) + float(timings.get("worker_total", 0.0))


def _check_cancelled(spec):
    if _cancelled(spec):
        raise RuntimeError("Coordinated update cancelled.")


def _bound_skin(spec, fallback):
    from core.draft_skin.protocol import read_result
    path = Path(spec.job_dir) / "bound_skin.npz"
    return read_result(path) if path.exists() else fallback


def _request(spec):
    request = json.loads(Path(spec.request_path).read_text(encoding="utf-8"))
    _TIMINGS["queue_wait"] = max(0.0, time.time() - float(request.get("dispatched_at", time.time())))
    return request
