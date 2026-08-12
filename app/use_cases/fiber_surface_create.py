from mathutils import Vector

from ..queries.root import root_for_context
from .results import failure, success
from .muscle_create import _compatibility_error, _mirror_rule, _new_muscle, _selected_fiber_ids, _sync_and_select_ctrl

try:
    from ...core.deps.dirty_hints import dirty_hints_for
    from ...core.id_utils import next_prefixed_id
    from ...core.vcp.fiber_modes import is_loop_fiber
    from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from ...core.visualization.fiber_surface_sync import evaluate_surface_record, find_fiber_surface_proxy
except ImportError:
    from core.deps.dirty_hints import dirty_hints_for
    from core.id_utils import next_prefixed_id
    from core.vcp.fiber_modes import is_loop_fiber
    from core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from core.visualization.fiber_surface_sync import evaluate_surface_record, find_fiber_surface_proxy


def create_fiber_surface(context, name="", close_across=False, use_mirrored_rows=False):
    root = root_for_context(context)
    payload = None if root is None else _creation_payload(context, root, use_mirrored_rows)
    if root is None:
        return failure("No AF_ROOT found.")
    if payload is None:
        return failure("Select Fibers for LOFT, or one LOOP Fiber for LOOP_PATCH.")
    fiber_ids, fibers, mode, mirrored, error = payload
    if error:
        return failure(error)
    surface = _new_surface(root.af_vcp_system, name, mode, close_across, mirrored)
    _assign_refs(surface, fiber_ids)
    _activate(root.af_vcp_system, surface.id)
    _sync_surface(root, context.scene, surface.id)
    _select_surface(context, root, surface.id)
    return success(f"Created {surface.id} from {len(fibers)} Fiber(s).", value=surface)


def _creation_payload(context, root, requested_mirror):
    fiber_ids = _selected_fiber_ids(context, root)
    by_id = {fiber.id: fiber for fiber in root.af_vcp_system.fibers}
    fibers = [by_id.get(fiber_id) for fiber_id in fiber_ids]
    if not fibers or any(fiber is None for fiber in fibers):
        return None
    mode = "LOOP_PATCH" if len(fibers) == 1 and is_loop_fiber(fibers[0]) else "LOFT"
    mirrored = bool(requested_mirror or _auto_mirror(root, fibers, mode))
    return fiber_ids, fibers, mode, mirrored, _surface_error(root, fibers, mode, mirrored)


def _auto_mirror(root, fibers, mode):
    return mode == "LOFT" and len(fibers) == 1 and _mirror_rule(root, fibers[0]) is not None


def _surface_error(root, fibers, mode, mirrored):
    if mode == "LOOP_PATCH":
        return "" if len(fibers) == 1 and is_loop_fiber(fibers[0]) else "LOOP_PATCH requires one LOOP Fiber."
    if len(fibers) == 1 and not mirrored:
        return "LOFT requires two Fibers or one mirrorable OPEN Fiber."
    return _compatibility_error(root, fibers)


def _new_surface(vcp, name, mode, close_across, mirrored):
    with suppress_vcp_prop_updates():
        surface = vcp.fiber_surfaces.add()
        surface.id = next_prefixed_id(vcp.fiber_surfaces, "SURFACE")
        surface.name = str(name or "").strip() or surface.id
        surface.construction_mode = mode
        surface.close_across_fibers = bool(close_across)
        surface.use_mirrored_rows = bool(mirrored)
    return surface


def _assign_refs(surface, fiber_ids):
    for fiber_id in fiber_ids:
        surface.fiber_refs.add().fiber_id = str(fiber_id)
    surface.active_fiber_ref_index = 0 if surface.fiber_refs else -1


def _activate(vcp, surface_id):
    vcp.active_vcp_type, vcp.active_vcp_id = "FIBER_SURFACE", str(surface_id)


def _sync_surface(root, scene, surface_id):
    _sync_scene()(root=root, scene=scene, dirty_hints=dirty_hints_for("FIBER_SURFACE", {surface_id}))


def _select_surface(context, root, surface_id):
    proxy = find_fiber_surface_proxy(context.scene, root.name, surface_id)
    if proxy is None:
        return
    for obj in tuple(context.selected_objects):
        obj.select_set(False)
    proxy.select_set(True)
    context.view_layer.objects.active = proxy


def create_muscle_from_fiber_surface(context, surface_id="", name=""):
    root = root_for_context(context)
    surface = None if root is None else _resolved_surface(context, root, surface_id)
    if root is None or surface is None:
        return failure("Select a Fiber Surface.")
    if str(surface.construction_mode) != "LOFT":
        return failure("Muscle creation currently requires a LOFT Fiber Surface.")
    muscle = _new_muscle(root.af_vcp_system, name, False, False)
    _commit_muscle_source(muscle, surface.id)
    root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "MUSCLE", muscle.id
    _sync_and_select_ctrl(context, root, muscle.id)
    return success(f"Created {muscle.id} from {surface.id}.", value=muscle)


def _resolved_surface(context, root, surface_id):
    selected = str(surface_id or _selected_surface_id(context, root) or root.af_vcp_system.active_vcp_id)
    return next((item for item in root.af_vcp_system.fiber_surfaces if item.id == selected), None)


def _selected_surface_id(context, root):
    obj = getattr(context, "active_object", None)
    valid = obj is not None and obj.get("af_root_name") == root.name and obj.get("af_fiber_surface_proxy")
    return str(obj.get("af_fiber_surface_id") or "") if valid else ""


def recompute_fiber_surface(context, surface_id=""):
    root = root_for_context(context)
    surface = None if root is None else _resolved_surface(context, root, surface_id)
    if surface is None:
        return failure("Fiber Surface not found.")
    _sync_surface(root, context.scene, surface.id)
    return success(f"Recomputed {surface.id}.", value=surface)


def select_fiber_surface_sources(context, surface_id=""):
    root = root_for_context(context)
    surface = None if root is None else _resolved_surface(context, root, surface_id)
    if surface is None:
        return failure("Fiber Surface not found.")
    objects = _fiber_proxy_map(context.scene, root.name)
    _select_objects(context, [objects.get(ref.fiber_id) for ref in surface.fiber_refs])
    return success(value=surface)


def convert_muscle_to_fiber_surface(context, muscle_id=""):
    root = root_for_context(context)
    muscle = None if root is None else _resolved_muscle(root, muscle_id)
    error = _conversion_preflight(muscle)
    if error:
        return failure(error)
    base = _muscle_base(context.scene, root.name, muscle.id)
    if base is None:
        return failure("Legacy Muscle BASE is unavailable.")
    return _convert_valid_muscle(context, root, muscle, base)


def _convert_valid_muscle(context, root, muscle, base):
    surface = _candidate_surface(root.af_vcp_system, muscle)
    result = _candidate_result(root, context.scene, surface)
    error = _parity_error(base, result)
    if error:
        _rollback_surface(root, context.scene, surface.id)
        return failure(error)
    _commit_muscle_source(muscle, surface.id)
    _release_legacy_ownership(root, muscle)
    return success(f"Converted {muscle.id} to {surface.id}.", value=surface)


def _candidate_result(root, scene, surface):
    try:
        return evaluate_surface_record(root, scene, surface)
    except Exception:
        return None


def _commit_muscle_source(muscle, surface_id):
    with suppress_vcp_prop_updates():
        muscle.surface_source_mode = "FIBER_SURFACE"
        muscle.fiber_surface_id = str(surface_id)


def _release_legacy_ownership(root, muscle):
    source_ids = {str(ref.fiber_id or "") for ref in muscle.fiber_refs}
    with suppress_vcp_prop_updates():
        muscle.fiber_refs.clear()
        muscle.active_fiber_ref_index = -1
        for fiber in root.af_vcp_system.fibers:
            if fiber.id in source_ids and fiber.muscle_id == muscle.id:
                fiber.muscle_id = ""


def _conversion_preflight(muscle):
    if muscle is None:
        return "Legacy Muscle not found."
    if str(muscle.surface_source_mode) != "LEGACY_FIBERS":
        return "Muscle already uses a Fiber Surface."
    return ""


def _resolved_muscle(root, muscle_id):
    target = str(muscle_id or root.af_vcp_system.active_vcp_id or "")
    return next((item for item in root.af_vcp_system.muscles if item.id == target), None)


def _candidate_surface(vcp, muscle):
    with suppress_vcp_prop_updates():
        surface = _new_surface(vcp, f"{muscle.name} Surface", "LOFT", muscle.closed_v, muscle.use_mirrored_rows)
        surface.flip_normals = bool(muscle.flip_normals)
        _assign_refs(surface, [ref.fiber_id for ref in muscle.fiber_refs])
    return surface


def _muscle_base(scene, root_name, muscle_id):
    return next((obj for obj in scene.objects if obj.get("af_muscle_proxy")
                 and obj.get("af_root_name") == root_name and obj.get("af_muscle_id") == muscle_id
                 and obj.get("af_muscle_surface") == "BASE"), None)


def _parity_error(legacy, candidate):
    if candidate is None:
        return "Fiber Surface evaluation failed."
    if len(legacy.data.vertices) != len(candidate.vertices):
        return f"Fiber Surface vertex count differs: legacy {len(legacy.data.vertices)}, candidate {len(candidate.vertices)}."
    if _mesh_faces(legacy) != tuple(candidate.faces):
        return "Fiber Surface topology or winding does not match legacy BASE."
    error = _maximum_world_error(legacy, candidate.vertices)
    return "Fiber Surface geometry differs from legacy BASE." if error > 2.0e-6 else ""


def _mesh_faces(obj):
    return tuple(tuple(poly.vertices) for poly in obj.data.polygons)


def _maximum_world_error(legacy, vertices):
    pairs = zip(legacy.data.vertices, vertices)
    return max(((legacy.matrix_world @ source.co) - Vector(target)).length for source, target in pairs)


def _rollback_surface(root, scene, surface_id):
    proxy = find_fiber_surface_proxy(scene, root.name, surface_id)
    _remove_object(proxy)
    surfaces = root.af_vcp_system.fiber_surfaces
    index = next((i for i, item in enumerate(surfaces) if item.id == surface_id), -1)
    if index >= 0:
        surfaces.remove(index)


def _remove_object(obj):
    if obj is None:
        return
    import bpy
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.meshes.remove(data)


def _fiber_proxy_map(scene, root_name):
    return {str(obj.get("af_fiber_id")): obj for obj in scene.objects
            if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name}


def _select_objects(context, objects):
    targets = [obj for obj in objects if obj is not None]
    for obj in tuple(context.selected_objects):
        obj.select_set(False)
    for obj in targets:
        obj.select_set(True)
    if targets:
        context.view_layer.objects.active = targets[-1]


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene
