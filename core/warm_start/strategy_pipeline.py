"""Strategy execution never generates topology or publishes Blender objects."""
import json
import time
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
import numpy as np
from ..mesh_issues import require_mesh, annotate
from .strategy_model import TopologyUpdateOutcome, TopologyUpdateStopped, TopologyCandidateRejected
from .strategy_registry import resolve_strategy, update_options
from .strategy_validation import validate_candidate


def run_topology_strategy(context, options=None, strategy=None):
    options = update_options(options)
    selected = resolve_strategy(options, strategy)
    _check_cancelled(context)
    started = time.perf_counter()
    try:
        result = _solve(context, options, selected)
        _check_cancelled(context)
        return _success(result, options, started)
    except (ValueError, RuntimeError, MemoryError) as error:
        _check_cancelled(context)
        return _rejection(error, options, started)


def _solve(context, options, strategy):
    if context.deformation_reference is not None:
        from ..deformation.pipeline import solve_final
        return solve_final(context, options, strategy)
    from .topology_solver import reset_projection_stats
    reset_projection_stats()
    _valid_inputs(context)
    _stored_structure(context)
    isolated = snapshot(replace(context, settings=options.settings))
    candidate = strategy.solve(isolated)
    report, metrics = _validated_candidate(context, candidate, options)
    from ..mesh_diagnostics import check_result
    return check_result(_result(context, candidate, report, metrics), context.cancelled)


def _validated_candidate(context, candidate, options):
    if not candidate.accepted:
        raise TopologyCandidateRejected(candidate.message or "Topology strategy rejected the update.",
                                        candidate.diagnostics)
    try:
        return validate_candidate(context, candidate, options)
    except ValueError as error:
        raise TopologyCandidateRejected(str(error), candidate.diagnostics) from error


def _valid_inputs(context):
    if context.topology is None or context.after_skin is None:
        raise ValueError("Topology update requires an existing topology and target skin.")
    if context.memory_budget > 0 and array_bytes(context, set()) > context.memory_budget:
        raise MemoryError("Topology strategy inputs exceed the worker memory budget.")
    for item in (context.topology, context.before_skin, context.after_skin):
        if item is not None:
            require_mesh(item.vertices, item.quads if hasattr(item, "quads") else item.triangles)
    if context.skin_update != "rebuilt" and context.before_skin is not None:
        if not np.array_equal(context.before_skin.triangles, context.after_skin.triangles):
            raise ValueError("Warm skin connectivity changed without a rebuild classification.")


def array_bytes(value, seen):
    if id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, np.ndarray):
        return value.nbytes
    if is_dataclass(value):
        return sum(array_bytes(getattr(value, item.name), seen) for item in fields(value))
    if isinstance(value, Mapping):
        return sum(array_bytes(item, seen) for item in value.values())
    if isinstance(value, (tuple, list)):
        return sum(array_bytes(item, seen) for item in value)
    return 0


def snapshot(value):
    from ..deformation.reference import DeformationReference
    if isinstance(value, DeformationReference):
        return value
    if isinstance(value, np.ndarray):
        view = value.view(); view.flags.writeable = False
        return view
    if is_dataclass(value):
        return replace(value, **{item.name: snapshot(getattr(value, item.name)) for item in fields(value)})
    if isinstance(value, dict):
        return {key: snapshot(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(snapshot(item) for item in value)
    return value


def _result(context, candidate, report, metrics):
    stats = dict(context.topology.statistics)
    stats.pop("update_deformation", None); stats.pop("issues", None)
    stats["last_update_type"] = "rebound" if context.skin_update == "rebuilt" else "warm"
    from .signatures import structural_signature
    stats["skin_structural_signature"] = structural_signature(len(context.after_skin.vertices), context.after_skin.triangles)
    stats["strategy_metrics"] = metrics
    stats["strategy_diagnostics"] = candidate.diagnostics
    _candidate_metadata(stats, candidate)
    return replace(context.topology, vertices=np.asarray(candidate.vertices).copy(), statistics=stats,
                   validation=report, skin_binding=candidate.skin_binding, guide_binding=candidate.guide_binding)


def _success(result, options, started):
    diagnostics = _diagnostics(options, started, "ACCEPTED", "Topology update accepted.")
    result.statistics["topology_strategy"] = diagnostics
    result.statistics["update_elapsed_seconds"] = diagnostics["elapsed_seconds"]
    result.statistics["diagnostics_deferred"] = result.statistics.get("intersection_check") != "COMPLETE"
    result.statistics["projection"] = result.statistics["strategy_diagnostics"].get("projection", {})
    result.statistics["arap_cache"] = result.statistics["strategy_diagnostics"].get("arap_cache", {})
    return TopologyUpdateOutcome(annotate(result, "topology_update"), diagnostics)


def _rejection(error, options, started):
    diagnostics = _diagnostics(options, started, "REJECTED", str(error))
    diagnostics["solver"] = getattr(error, "diagnostics", {})
    return TopologyUpdateOutcome(None, diagnostics)


def _diagnostics(options, started, status, message):
    from ..draft_skin.resources import memory_metrics
    from dataclasses import asdict
    import hashlib
    signature = hashlib.sha256(json.dumps(asdict(options), sort_keys=True).encode()).hexdigest()
    return {"name": options.strategy, "version": options.version, "module": options.module,
            "settings": options.settings, "failure_policy": options.failure_policy,
            "maximum_surface_error": options.maximum_surface_error, "status": status,
            "message": message, "configuration_signature": signature,
            "elapsed_seconds": time.perf_counter() - started, **memory_metrics()}


def require_rebuild_allowed(options=None, diagnostics=None):
    options = update_options(options)
    if options.failure_policy == "STOP":
        raise TopologyUpdateStopped(diagnostics or {"status": "REBUILD_REQUIRED",
            "message": "Topology rebuild required; STOP policy preserves the previous outputs.",
            "name": options.strategy, "version": options.version, "failure_policy": "STOP"})


def _check_cancelled(context):
    if context.cancelled is not None and context.cancelled():
        raise RuntimeError("Coordinated update cancelled.")


def _stored_structure(context):
    from .signatures import structural_signature
    old = context.topology
    expected = old.statistics.get("structural_signature", "")
    if expected and expected != structural_signature(len(old.vertices), old.quads):
        raise ValueError("Stored topology connectivity changed; fixed-topology update is unavailable.")
    before = context.before_skin
    expected = old.statistics.get("skin_structural_signature", "")
    if before is not None and expected and expected != structural_signature(len(before.vertices), before.triangles):
        raise ValueError("Topology bindings do not match their reference skin.")


def _candidate_metadata(stats, candidate):
    stats["warnings"] = list(stats.get("warnings", ()))
    if candidate.message:
        stats.setdefault("warnings", []).append(candidate.message)
    json.dumps(candidate.diagnostics, allow_nan=False)
    if candidate.deformation is not None:
        json.dumps(candidate.deformation, allow_nan=False)
        stats["update_deformation"] = candidate.deformation
