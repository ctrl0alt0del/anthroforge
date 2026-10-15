"""Blender capture adapter for the shared strategy pipeline."""
import numpy as np


def solve_update(root, scene, capture, skin_update, options=None, before_skin=None, predicted=None):
    from ..warm_update.current_output import current_skin_result, current_topology_result, bound_skin_result
    Context, run, guard, parse = _api()
    skin, old = current_skin_result(root, scene), current_topology_result(root, scene)
    before_skin = before_skin if before_skin is not None else bound_skin_result(root, scene)
    skin_update = binding_update_type(before_skin, skin, skin_update)
    context = Context(old, before_skin, skin, capture, skin_update, predicted=predicted)
    outcome = run(context, options)
    if outcome.result is None:
        guard(parse(options), outcome.diagnostics)
    return old, outcome


def _api():
    from ..draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()
    if __package__.startswith("anthroforge."):
        from ...core.warm_start.strategy_model import TopologyUpdateContext
        from ...core.warm_start.strategy_pipeline import run_topology_strategy, require_rebuild_allowed
        from ...core.warm_start.strategy_registry import update_options
    else:
        from core.warm_start.strategy_model import TopologyUpdateContext
        from core.warm_start.strategy_pipeline import run_topology_strategy, require_rebuild_allowed
        from core.warm_start.strategy_registry import update_options
    return TopologyUpdateContext, run_topology_strategy, require_rebuild_allowed, update_options


def legacy_result(old, outcome, rebound=False):
    from .warm import WarmUpdateStatus, WarmInvalidationReason, WarmValidationReport
    valid, message = outcome.result is not None, outcome.diagnostics["message"]
    result = outcome.result or old
    reason = WarmInvalidationReason.NONE if valid else WarmInvalidationReason.VALIDATION_FAILED
    status = WarmUpdateStatus(valid, "Rebound" if rebound else "Complete", 1.0, message, reason)
    quality = bool(result.validation and result.validation.valid)
    report = WarmValidationReport(quality, bool(np.isfinite(result.vertices).all()), quality, True, 1.0,
                                  message=message)
    if rebound:
        return result.vertices, result.skin_binding, result.guide_binding, status, report
    return result.vertices, status, report


def apply_result(obj, outcome):
    if outcome.result is None:
        return
    from .warm import apply_topology_vertices, _write_rebindings
    import json
    result = outcome.result
    apply_topology_vertices(obj, result.vertices)
    _write_rebindings(obj.data, result.skin_binding, result.guide_binding)
    obj["af_topology_stats_json"] = json.dumps(result.statistics, sort_keys=True)
    _publish_issues(obj, result)


def _publish_issues(obj, result):
    import bpy
    from ..mesh_issues import persist, publish, bind_reference
    persist(obj, result, "topology_update")
    for scene in obj.users_scene:
        root = scene.objects.get(obj.get("af_root_name", ""))
        if root is not None:
            bind_reference(scene, root, obj); publish(obj, scene, root)


def binding_update_type(before, after, update_type):
    if before is not None and after is not None and not np.array_equal(before.triangles, after.triangles):
        return "rebuilt"
    return update_type
