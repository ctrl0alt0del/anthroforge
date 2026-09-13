"""Resolve fresh warning references and use selection-only native handle refresh."""
import bpy
from ..warnings import session
from ..warnings.anchors import identity
from ..utils import set_active_af_root
from .warning_runtime import resolve_root, schedule_root


def select_warning(context, warning_id):
    warning = session.REPOSITORY.records.get(warning_id)
    if warning is None:
        return False
    scene, root = resolve_root(warning.entity.scope)
    entity = resolve_entity(root, warning.entity)
    if not fresh(warning, scene, root, entity):
        if root is not None:
            schedule_root(scene, root, {warning.entity.native_id})
        return False
    try:
        return activate(context, scene, root, entity, warning)
    except (RuntimeError, ReferenceError, ValueError):
        schedule_root(scene, root, {warning.entity.native_id})
        return False


def resolve_entity(root, ref):
    names = {"FIBER": "fibers", "MUSCLE": "muscles", "FIBER_SURFACE": "fiber_surfaces",
             "BLOB": "blobs", "SOFT_TISSUE": "soft_tissues", "SCP": "scps"}
    system = getattr(root, "af_scp_system" if ref.kind == "SCP" else "af_vcp_system", None)
    rows = [row for row in getattr(system, names.get(ref.kind, ""), ()) if str(row.id) == ref.native_id]
    return rows[0] if len(rows) == 1 else None


def fresh(warning, scene, root, entity):
    state = session.REPOSITORY.states.get(warning.entity.scope, {})
    if entity is None or state.get("status") != "COMPLETE":
        return False
    ref = session.entity_reference(scene, root, entity, warning.entity.kind)
    if ref.scope != warning.entity.scope:
        return False
    if warning.pin is None:
        return True
    _ref, (revision, signature) = identity(scene, root, entity)
    return (revision, signature) == (warning.pin.attachment_revision, warning.pin.fingerprint)


def activate(context, scene, root, entity, warning):
    if context.window is None:
        return False
    context.window.scene = scene
    layer = context.window.view_layer
    if root.name not in layer.objects:
        return False
    set_active_af_root(scene, root)
    prepare_selection(scene, root, layer)
    target = select_target(context, scene, root, entity, warning)
    if target is None or target.name not in scene.objects or target.name not in layer.objects:
        raise ValueError("Warning target is unavailable in the scene/view layer")
    return select_object(layer, target)


def select_object(layer, target):
    for obj in layer.objects:
        if obj is not None:
            obj.select_set(False)
    target.hide_set(False); target.select_set(True)
    layer.objects.active = target
    return True


def prepare_selection(scene, root, layer):
    scene.af_selection_sync_lock = True
    try:
        root.af_scp_system.active_scp_index = -1
        layer.objects.active = root
    finally:
        scene.af_selection_sync_lock = False


def select_target(context, scene, root, entity, warning):
    from ..vcp.prop_update_guard import suppress_vcp_prop_updates
    if warning.entity.kind == "SCP":
        return scp_target(scene, root, entity)
    with suppress_vcp_prop_updates():
        root.af_vcp_system.active_vcp_type = warning.entity.kind
        root.af_vcp_system.active_vcp_id = entity.id
    if warning.entity.kind == "FIBER":
        from .fiber_sync import register_fiber_sync
        sync = register_fiber_sync()
        sync.refresh_selection(root, scene, context.window_manager, {entity.id}, sync_handles=True)
        return fiber_target(sync, scene, root, entity, warning.pin)
    key = "af_" + warning.entity.kind.lower() + "_id"
    return next((obj for obj in scene.objects if obj.get("af_root_name") == root.name
                 and obj.get(key) == entity.id), None)


def fiber_target(sync, scene, root, fiber, pin):
    from .fiber_sync_helpers import find_fiber_proxy
    collection = sync._get_vis_collection(scene)
    if pin is None:
        return find_fiber_proxy(collection, root.name, fiber.id)
    if pin.role == "TOUCH":
        return sync._find_touch_handle(collection, root.name, fiber.id, pin.index - 1)
    if pin.role == "LOOP":
        return sync._find_loop_anchor_handle(collection, root.name, fiber.id, pin.index)
    return sync._find_endpoint_handle(collection, root.name, fiber.id, pin.role[-1])


def scp_target(scene, root, entity):
    scene.af_selection_sync_lock = True
    try:
        root.af_scp_system.active_scp_index = next(i for i, row in enumerate(root.af_scp_system.scps) if row.id == entity.id)
    finally:
        scene.af_selection_sync_lock = False
    return next((obj for obj in scene.objects if obj.get("af_root_name") == root.name
                 and obj.get("af_scp_id") == entity.id and obj.get("af_scp_geometry")), None)
