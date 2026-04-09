import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..registry import SCPRegistry
from ..utils import get_af_root
from ..attachment_codec import encode_fiber_mesh_anchor, encode_fiber_shape_param


def _iter_endpoints(fiber):
    return (
        ("A", fiber.a_parent_id, fiber.a_attach_param),
        ("B", fiber.b_parent_id, fiber.b_attach_param),
    )


def _sync_endpoint_handle(sync, vis_col, root, scene, runtime_registry, fiber, endpoint, parent_id, raw):
    h = sync._find_endpoint_handle(vis_col, root.name, fiber.id, endpoint)
    if h is None:
        h = sync._create_endpoint_handle(vis_col, root, fiber.id, endpoint)
    w = sync._endpoint_world(root, scene, runtime_registry, parent_id, raw)
    if w is not None:
        h.location = w
        sync._set_helper_screen_size(h, px=14.0)


def _sync_touch_handle(sync, vis_col, root, scene, runtime_registry, fiber, index, touch):
    h = sync._find_touch_handle(vis_col, root.name, fiber.id, index)
    if h is None:
        h = sync._create_touch_handle(vis_col, root, fiber.id, index)
    w = sync._endpoint_world(root, scene, runtime_registry, touch.parent_id, touch.attach_param)
    if w is not None:
        h.location = w
        sync._set_helper_screen_size(h, px=12.0)


def _cleanup_stale_handles(vis_col, root_name, live_endpoint_keys, live_touch_keys):
    for obj in list(vis_col.objects):
        if obj.get("af_fiber_endpoint_handle") and obj.get("af_root_name") == root_name:
            key = (obj.get("af_fiber_id"), obj.get("af_fiber_endpoint"))
            if key not in live_endpoint_keys:
                bpy.data.objects.remove(obj, do_unlink=True)
        if obj.get("af_fiber_touch_handle") and obj.get("af_root_name") == root_name:
            key = (obj.get("af_fiber_id"), int(obj.get("af_fiber_touch_index", -1)))
            if key not in live_touch_keys:
                bpy.data.objects.remove(obj, do_unlink=True)


def sync_handles(sync, root, scene, vis_col, runtime_registry):
    live_endpoint_keys = set()
    live_touch_keys = set()

    for fiber in root.af_vcp_system.fibers:
        for endpoint, pid, raw in _iter_endpoints(fiber):
            live_endpoint_keys.add((fiber.id, endpoint))
            _sync_endpoint_handle(sync, vis_col, root, scene, runtime_registry, fiber, endpoint, pid, raw)

        for i, tp in enumerate(fiber.mid_touches):
            live_touch_keys.add((fiber.id, i))
            _sync_touch_handle(sync, vis_col, root, scene, runtime_registry, fiber, i, tp)
    _cleanup_stale_handles(vis_col, root.name, live_endpoint_keys, live_touch_keys)


def apply_selection_highlight(sync, root, scene):
    active_id = root.af_vcp_system.active_vcp_id
    active_type = root.af_vcp_system.active_vcp_type
    for obj in scene.objects:
        if not obj.get("af_fiber_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        base = tuple(obj.get("af_fiber_base_color", sync.default_fiber_color))
        sync._set_fiber_color(
            obj,
            sync.selected_fiber_color if active_type == "FIBER" and obj.get("af_fiber_id") == active_id else base,
        )


def _fibers_to_sync(root, target_fiber_ids):
    if target_fiber_ids is None:
        return list(root.af_vcp_system.fibers)
    target_set = set(target_fiber_ids)
    return [f for f in root.af_vcp_system.fibers if f.id in target_set]


def _sync_single_fiber(sync, vis_col, root, scene, depsgraph, fiber, bake):
    obj = sync._find_fiber_proxy(vis_col, root.name, fiber.id)
    if obj is None:
        obj = sync._create_fiber_proxy(vis_col, root, fiber.id)
    use_bake = bool(bake or sync._fiber_prefer_bake(fiber))
    points = sync._solver.solve_points(root=root, fiber_prop=fiber, scene=scene, depsgraph=depsgraph, bake=use_bake)
    if len(points) >= 2:
        sync._update_curve_points(obj, points, fiber.thickness, bake=use_bake)


def _cleanup_stale_fiber_proxies(vis_col, root_name, live_ids):
    for obj in list(vis_col.objects):
        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") not in live_ids:
            bpy.data.objects.remove(obj, do_unlink=True)


def sync_root_to_scene(sync, root=None, scene=None, bake=False, target_fiber_ids=None):
    if sync._syncing:
        return
    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        runtime = SCPRegistry(root)
        runtime.build()

        fibers_to_sync = _fibers_to_sync(root, target_fiber_ids)

        live_ids = set()
        for fiber in fibers_to_sync:
            live_ids.add(fiber.id)
            _sync_single_fiber(sync, vis_col, root, scene, depsgraph, fiber, bake)

        _cleanup_stale_fiber_proxies(vis_col, root.name, {f.id for f in root.af_vcp_system.fibers})

        sync._sync_handles(root, scene, vis_col, runtime.registry)
        sync._apply_selection_highlight(root, scene)
    finally:
        sync._syncing = False


def _find_fiber(root, fiber_id):
    return next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)


def _compute_attach_raw(sync, parent_scp, parent_proxy, moved_world):
    if getattr(parent_scp.shape, "type_id", "") == "MESH_ASSET":
        local_pt = sync._nearest_parent_mesh_vertex_local_point(parent_proxy, moved_world)
        return None if local_pt is None else encode_fiber_mesh_anchor(local_pt)
    param = sync._nearest_param(parent_scp, parent_proxy, moved_world)
    return encode_fiber_shape_param(param)


def _update_endpoint_handle(sync, root, scene, runtime, obj, changed_ids):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    endpoint = obj.get("af_fiber_endpoint")
    if fiber is None:
        return False
    parent_id = fiber.a_parent_id if endpoint == "A" else fiber.b_parent_id
    parent_scp = runtime.registry.get(parent_id)
    parent_proxy = sync._get_scp_proxy(scene, root.name, parent_id)
    if parent_scp is None or parent_proxy is None:
        return False
    raw = _compute_attach_raw(sync, parent_scp, parent_proxy, obj.location.copy())
    if raw is None:
        return False
    slot = "a_attach_param" if endpoint == "A" else "b_attach_param"
    if getattr(fiber, slot) == raw:
        return False
    setattr(fiber, slot, raw)
    sync._set_fiber_prefer_bake(fiber, False)
    changed_ids.add(fiber.id)
    return True


def _update_touch_handle(sync, root, scene, runtime, obj, changed_ids):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    touch_index = int(obj.get("af_fiber_touch_index", -1))
    if fiber is None or touch_index < 0 or touch_index >= len(fiber.mid_touches):
        return False
    tp = fiber.mid_touches[touch_index]
    parent_scp = runtime.registry.get(tp.parent_id)
    parent_proxy = sync._get_scp_proxy(scene, root.name, tp.parent_id)
    if parent_scp is None or parent_proxy is None:
        return False
    raw = _compute_attach_raw(sync, parent_scp, parent_proxy, obj.location.copy())
    if raw is None or tp.attach_param == raw:
        return False
    tp.attach_param = raw
    sync._set_fiber_prefer_bake(fiber, False)
    changed_ids.add(fiber.id)
    return True


def _is_relevant_update_obj(sync, root, vis_col, obj):
    if not isinstance(obj, bpy.types.Object):
        return False
    if obj.get("af_root_name") != root.name:
        return False
    return vis_col.objects.get(obj.name) is not None


def _collect_changed_fiber_ids(sync, root, scene, depsgraph, vis_col, runtime):
    changed_fiber_ids = set()
    for upd in depsgraph.updates:
        obj = upd.id
        if not _is_relevant_update_obj(sync, root, vis_col, obj):
            continue
        if obj.get("af_fiber_endpoint_handle"):
            _update_endpoint_handle(sync, root, scene, runtime, obj, changed_fiber_ids)
        elif obj.get("af_fiber_touch_handle"):
            _update_touch_handle(sync, root, scene, runtime, obj, changed_fiber_ids)
    return changed_fiber_ids


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return
    root = get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return

    runtime = SCPRegistry(root)
    runtime.build()

    sync._syncing = True
    try:
        changed_fiber_ids = _collect_changed_fiber_ids(sync, root, scene, depsgraph, vis_col, runtime)
    finally:
        sync._syncing = False

    if changed_fiber_ids:
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("FIBER", changed_fiber_ids),
            source="depsgraph",
            event_type="TRANSFORM",
        )
