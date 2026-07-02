from ..queries.root import root_for_context
from .results import failure, success

try:
    from ...core.vcp.fiber_modes import is_loop_fiber
    from ...core.id_utils import next_prefixed_id
    from ...core.visualization.mirror_rules import effective_rule_for_fiber
    from ...core.vcp.runtime_state import reset_muscle_runtime
except ImportError:
    from core.vcp.fiber_modes import is_loop_fiber
    from core.id_utils import next_prefixed_id
    from core.visualization.mirror_rules import effective_rule_for_fiber
    from core.vcp.runtime_state import reset_muscle_runtime


def create_muscle_vcp(context, name="", closed_v=False, use_mirrored_rows=False):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    payload = _creation_payload(context, root)
    if payload is None:
        return failure("Select at least 2 fiber proxies in viewport (Shift-select).")
    fiber_ids, fiber_map, error, auto_mirror = payload
    if error:
        return failure(error)
    muscle = _new_muscle(root.af_vcp_system, name, closed_v, use_mirrored_rows or auto_mirror)
    _assign_fibers(root.af_vcp_system, muscle, fiber_ids, fiber_map)
    _activate(root.af_vcp_system, "MUSCLE", muscle.id)
    _sync_and_select_ctrl(context, root, muscle.id)
    return success(f"Created {muscle.id} from {len(fiber_ids)} fibers", value=muscle)


def _creation_payload(context, root):
    fiber_ids = _selected_fiber_ids(context, root)
    auto_mirror = _auto_mirror_rows(root, fiber_ids)
    if len(fiber_ids) < 2 and not auto_mirror:
        return None
    fibers_by_id, fibers, error = _resolved_fibers(root.af_vcp_system, fiber_ids)
    error = error or _compatibility_error(root, fibers or ())
    return fiber_ids, fibers_by_id, error, auto_mirror


def _auto_mirror_rows(root, fiber_ids):
    fiber = _single_selected_fiber(root, fiber_ids)
    return fiber is not None and not is_loop_fiber(fiber) and _mirror_rule(root, fiber) is not None


def _single_selected_fiber(root, fiber_ids):
    if len(fiber_ids) != 1:
        return None
    return _fiber_map(root).get(str(fiber_ids[0] or ""))


def _mirror_rule(root, fiber):
    return effective_rule_for_fiber(fiber, _scp_map(root))


def _scp_map(root):
    return {str(scp.id or ""): scp for scp in getattr(getattr(root, "af_scp_system", None), "scps", ())}


def _fiber_map(root):
    return {str(fiber.id or ""): fiber for fiber in getattr(getattr(root, "af_vcp_system", None), "fibers", ())}


def _selected_fiber_ids(context, root):
    seen, out = set(), []
    items = _ordered_selected_objects()(context.scene, getattr(context, "selected_objects", ()), getattr(context, "active_object", None))
    for obj in items:
        fiber_id = _selected_proxy_fiber_id(obj, root.name)
        if fiber_id and fiber_id not in seen:
            seen.add(fiber_id)
            out.append(fiber_id)
    return out


def _selected_proxy_fiber_id(obj, root_name):
    valid = obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name
    return obj.get("af_fiber_id") if valid else None


def _ordered_selected_objects():
    try:
        from ...core.selection_order import ordered_selected_objects
    except ImportError:
        from core.selection_order import ordered_selected_objects
    return ordered_selected_objects


def _resolved_fibers(vcp, fiber_ids):
    fibers_by_id = {fiber.id: fiber for fiber in vcp.fibers}
    fibers = [fibers_by_id.get(fid) for fid in fiber_ids]
    missing = next((fid for fid, fiber in zip(fiber_ids, fibers) if fiber is None), "")
    return (None, None, f"Fiber '{missing}' not found.") if missing else (fibers_by_id, fibers, "")


def _compatibility_error(root, fibers):
    _ = root
    if _mixed_topology(fibers):
        return "Do not mix open and loop fibers in one muscle."
    node_count = int(fibers[0].node_count)
    for fiber in fibers[1:]:
        if int(fiber.node_count) != node_count:
            return "Selected fibers must have identical node_count."
    return ""


def _mixed_topology(fibers):
    return any(is_loop_fiber(fiber) != is_loop_fiber(fibers[0]) for fiber in fibers[1:])


def _new_muscle(vcp, name, closed_v, use_mirrored_rows):
    muscle = vcp.muscles.add()
    muscle.id = next_prefixed_id(vcp.muscles, "MUSCLE")
    muscle.name = str(name or "").strip() or muscle.id
    muscle.closed_v = bool(closed_v)
    muscle.use_mirrored_rows = bool(use_mirrored_rows)
    _apply_values(muscle, _muscle_defaults())
    reset_muscle_runtime(muscle)
    return muscle


def _muscle_defaults():
    return {
        "inflation_enabled": True,
        "inflation_mode": "CTRL_POINT",
        "inflation_max_value": 0.05,
        "inflation_falloff_type": "GAUSSIAN",
        "inflation_falloff_radius": 0.2,
    }


def _apply_values(item, values):
    for key, value in values.items():
        setattr(item, key, value)


def _assign_fibers(vcp, muscle, fiber_ids, fibers_by_id):
    for fiber_id in fiber_ids:
        _detach_fiber(vcp, muscle.id, fiber_id)
        ref = muscle.fiber_refs.add()
        ref.fiber_id = fiber_id
        fibers_by_id[fiber_id].muscle_id = muscle.id
    muscle.active_fiber_ref_index = 0 if muscle.fiber_refs else -1


def _detach_fiber(vcp, muscle_id, fiber_id):
    for muscle in vcp.muscles:
        if muscle.id == muscle_id:
            continue
        for index in reversed(_ref_indexes(muscle, fiber_id)):
            muscle.fiber_refs.remove(index)


def _ref_indexes(muscle, fiber_id):
    return [index for index, ref in enumerate(muscle.fiber_refs) if ref.fiber_id == fiber_id]


def _activate(vcp, kind, entity_id):
    vcp.active_vcp_type, vcp.active_vcp_id = str(kind or ""), str(entity_id or "")


def _sync_entity(root, scene, kind, entity_ids):
    hints = _dirty_hints_for()(kind, entity_ids)
    _sync_scene()(root=root, scene=scene, dirty_hints=hints)


def _select_if_found(context, obj):
    if obj is None:
        return
    for item in getattr(context, "selected_objects", ()):
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _find_ctrl(scene, root_name, muscle_id):
    vis_col = _vis_collection()(scene)
    return _find_inflation_ctrl()(vis_col, root_name, muscle_id)


def _find_proxy(scene, root_name, muscle_id):
    for obj in getattr(scene, "objects", ()):
        valid = obj.get("af_muscle_proxy") and obj.get("af_root_name") == root_name
        if valid and obj.get("af_muscle_id") == muscle_id and obj.get("af_muscle_surface") == "BASE":
            return obj
    return None


def _sync_and_select_ctrl(context, root, muscle_id):
    _sync_entity(root, context.scene, "MUSCLE", {muscle_id})
    proxy = _find_proxy(context.scene, root.name, muscle_id)
    _select_if_found(context, proxy)
    _sync_entity(root, context.scene, "MUSCLE", {muscle_id}) if proxy is not None else None
    _select_if_found(context, _find_ctrl(context.scene, root.name, muscle_id))


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def _vis_collection():
    try:
        from ...core.visualization.muscle_sync_helpers import get_vis_collection
    except ImportError:
        from core.visualization.muscle_sync_helpers import get_vis_collection
    return lambda scene: get_vis_collection(scene, "AF_VCP_VIS")


def _find_inflation_ctrl():
    try:
        from ...core.visualization.muscle_sync_helpers import find_inflation_ctrl
    except ImportError:
        from core.visualization.muscle_sync_helpers import find_inflation_ctrl
    return find_inflation_ctrl
