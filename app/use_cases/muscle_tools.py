from ..queries.root import root_for_context
from .results import failure, success

try:
    from ...core.visualization.muscle_inflation_modes import muscle_inflation_behavior
except ImportError:
    from core.visualization.muscle_inflation_modes import muscle_inflation_behavior


def flip_muscle_normals(context, muscle_id=""):
    root = root_for_context(context)
    vcp, muscle, error = _resolved_muscle(root, muscle_id)
    if muscle is None:
        return failure(error)
    if getattr(muscle, "inflation_mode", "CTRL_POINT") == "SECTION_PROFILE":
        from .muscle_profile import configure, action_configuration
        configure(root, context.scene, muscle.id, action_configuration(muscle, "side"))
        return success(value=muscle)
    target, kind = _normal_target(vcp, muscle)
    target.flip_normals = not target.flip_normals
    _sync_entity(root, context.scene, kind, {target.id})
    return success(value=muscle)


def _normal_target(vcp, muscle):
    if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) != "FIBER_SURFACE":
        return muscle, "MUSCLE"
    target = str(getattr(muscle, "fiber_surface_id", "") or "")
    surface = next((item for item in vcp.fiber_surfaces if item.id == target), None)
    return (surface, "FIBER_SURFACE") if surface is not None else (muscle, "MUSCLE")


def select_muscle_inflation_ctrl(context, muscle_id=""):
    root = root_for_context(context)
    vcp, muscle, error = _resolved_muscle(root, muscle_id)
    if muscle is None:
        return failure(error)
    ctrl, error = _selected_ctrl_for_mode(context, root, vcp, muscle)
    if ctrl is None:
        return failure(error or "Inflation control not found.")
    return success(value=ctrl)


def _selected_ctrl_for_mode(context, root, vcp, muscle):
    control = muscle_inflation_behavior(muscle).control
    return control.select_control(context, root, vcp, muscle, _resolved_ctrl)


def _resolved_muscle(root, muscle_id):
    if root is None:
        return None, None, ""
    vcp = root.af_vcp_system
    target_id = str(muscle_id or vcp.active_vcp_id or "")
    if not target_id:
        return vcp, None, "Muscle not found."
    muscle = next((item for item in vcp.muscles if item.id == target_id), None)
    return vcp, muscle, "" if muscle is not None else "Muscle not found."


def _find_ctrl(scene, root_name, muscle_id):
    vis_col = _muscle_vis_collection()(scene)
    return _find_inflation_ctrl()(vis_col, root_name, muscle_id)


def _find_proxy(scene, root_name, muscle_id):
    vis_col = _muscle_vis_collection()(scene)
    return _find_muscle_proxy()(vis_col, root_name, muscle_id, "BASE")


def _resolved_ctrl(context, root, vcp, muscle):
    _activate_vcp(vcp, "MUSCLE", muscle.id)
    previous = _active_object(context)
    _sync_entity(root, context.scene, "MUSCLE", {muscle.id})
    proxy = _find_proxy(context.scene, root.name, muscle.id)
    if proxy is None:
        return None
    _set_active_object(context, proxy)
    _sync_entity(root, context.scene, "MUSCLE", {muscle.id})
    ctrl = _find_ctrl(context.scene, root.name, muscle.id)
    _set_active_object(context, previous if ctrl is None else ctrl)
    return None if ctrl is None else _select_only(context, ctrl)


def _select_only(context, obj):
    for item in tuple(getattr(context, "selected_objects", ())):
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def _activate_vcp(vcp, kind, entity_id):
    vcp.active_vcp_type, vcp.active_vcp_id = str(kind or ""), str(entity_id or "")


def _active_object(context):
    objects = getattr(getattr(context, "view_layer", None), "objects", None)
    return None if objects is None else getattr(objects, "active", None)


def _set_active_object(context, obj):
    objects = getattr(getattr(context, "view_layer", None), "objects", None)
    if objects is not None:
        objects.active = obj


def _sync_entity(root, scene, kind, entity_ids):
    hints = _dirty_hints_for()(kind, entity_ids)
    _sync_scene()(root=root, scene=scene, dirty_hints=hints)


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


def _muscle_vis_collection():
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


def _find_muscle_proxy():
    try:
        from ...core.visualization.muscle_sync_helpers import find_muscle_proxy
    except ImportError:
        from core.visualization.muscle_sync_helpers import find_muscle_proxy
    return find_muscle_proxy
