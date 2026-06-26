import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..deps.controls import classify_control_object, enqueue_control_intent
from ..deps.conflict_resolver import resolve_conflict
from ..vcp.fiber_modes import is_derived_loop, is_open_fiber
from ..utils import depsgraph_for_scene, get_af_root, scene_for_id
from ..attachment_codec import encode_fiber_mesh_anchor
from .control_runtime import active_entity_id


def _iter_endpoints(fiber):
    return (
        ("A", fiber.a_parent_id, fiber.a_attach_param),
        ("B", fiber.b_parent_id, fiber.b_attach_param),
    )


def _sync_endpoint_handle(sync, vis_col, root, scene, runtime_registry, fiber, endpoint, parent_id, raw, window_manager=None):
    h = sync._find_endpoint_handle(vis_col, root.name, fiber.id, endpoint)
    if h is None:
        h = sync._create_endpoint_handle(vis_col, root, fiber.id, endpoint)
    w = sync._endpoint_world(root, scene, runtime_registry, parent_id, raw)
    if w is not None:
        h.location = w
        sync._set_helper_screen_size(h, px=14.0, window_manager=window_manager)


def _sync_touch_handle(sync, vis_col, root, scene, runtime_registry, fiber, index, touch, window_manager=None):
    h = sync._find_touch_handle(vis_col, root.name, fiber.id, index)
    if h is None:
        h = sync._create_touch_handle(vis_col, root, fiber.id, index)
    w = sync._endpoint_world(root, scene, runtime_registry, touch.parent_id, touch.attach_param)
    if w is not None:
        h.location = w
        sync._set_helper_screen_size(h, px=12.0, window_manager=window_manager)


def _cleanup_stale_handles(vis_col, root_name, live_endpoint_keys, live_touch_keys):
    for obj in list(vis_col.objects):
        if _safe_get(obj, "af_fiber_endpoint_handle") and _safe_get(obj, "af_root_name") == root_name:
            key = (_safe_get(obj, "af_fiber_id"), _safe_get(obj, "af_fiber_endpoint"))
            if key not in live_endpoint_keys:
                bpy.data.objects.remove(obj, do_unlink=True)
        if _safe_get(obj, "af_fiber_touch_handle") and _safe_get(obj, "af_root_name") == root_name:
            key = (_safe_get(obj, "af_fiber_id"), int(_safe_get(obj, "af_fiber_touch_index", -1)))
            if key not in live_touch_keys:
                bpy.data.objects.remove(obj, do_unlink=True)


def _safe_get(obj, key, default=None):
    try:
        return obj.get(key, default)
    except ReferenceError:
        return default


def _active_fiber_id(root, scene=None, active_object=None):
    return active_entity_id(root, "FIBER", scene, active_object)


def _active_fiber(root, scene):
    fiber_id = _active_fiber_id(root, scene)
    return None if not fiber_id else _find_fiber(root, fiber_id)


def sync_handles(sync, root, scene, vis_col, runtime_registry, window_manager=None):
    live_endpoint_keys = set()
    live_touch_keys = set()
    fiber = _active_fiber(root, scene)
    if fiber is not None and is_open_fiber(fiber):
        _sync_fiber_handles(sync, root, scene, vis_col, runtime_registry, fiber, live_endpoint_keys, live_touch_keys, window_manager)
    _cleanup_stale_handles(vis_col, root.name, live_endpoint_keys, live_touch_keys)


def _sync_fiber_handles(sync, root, scene, vis_col, runtime_registry, fiber, live_endpoint_keys, live_touch_keys, window_manager=None):
    for endpoint, pid, raw in _iter_endpoints(fiber):
        live_endpoint_keys.add((fiber.id, endpoint))
        _sync_endpoint_handle(sync, vis_col, root, scene, runtime_registry, fiber, endpoint, pid, raw, window_manager)
    for i, tp in enumerate(fiber.mid_touches):
        live_touch_keys.add((fiber.id, i))
        _sync_touch_handle(sync, vis_col, root, scene, runtime_registry, fiber, i, tp, window_manager)


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
        return _ordered_fibers(root.af_vcp_system.fibers)
    target_set = set(target_fiber_ids)
    return _ordered_fibers([f for f in root.af_vcp_system.fibers if f.id in target_set])


def _ordered_fibers(fibers):
    return sorted(tuple(fibers or ()), key=lambda fiber: (1 if is_derived_loop(fiber) else 0, str(fiber.id or "")))


def _sync_single_fiber(sync, vis_col, root, scene, depsgraph, fiber, bake):
    obj = sync._find_fiber_proxy(vis_col, root.name, fiber.id)
    if obj is None:
        obj = sync._create_fiber_proxy(vis_col, root, fiber.id)
    use_bake = bool(bake or sync._fiber_prefer_bake(fiber))
    points = sync._solver.solve_points(root=root, fiber_prop=fiber, scene=scene, depsgraph=depsgraph, bake=bool(bake))
    if len(points) >= 2:
        sync._update_curve_points(obj, points, fiber.thickness, bake=use_bake, cyclic=sync._fiber_cyclic(fiber))


def _cleanup_stale_fiber_proxies(vis_col, root_name, live_ids):
    for obj in list(vis_col.objects):
        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") not in live_ids:
            bpy.data.objects.remove(obj, do_unlink=True)


def _sync_inputs(root, scene):
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    depsgraph = depsgraph_for_scene(scene)
    return root, scene, depsgraph


def sync_root_to_scene(sync, root=None, scene=None, bake=False, target_fiber_ids=None, window_manager=None):
    if sync._syncing:
        return
    state = _scene_sync_state(root, scene)
    if state is None:
        return
    _run_scene_sync(sync, *state, bake, target_fiber_ids, window_manager)


def _scene_sync_state(root, scene):
    root, scene, depsgraph = _sync_inputs(root, scene)
    return None if root is None or depsgraph is None or not hasattr(root, "af_vcp_system") else (root, scene, depsgraph)


def _run_scene_sync(sync, root, scene, depsgraph, bake, target_fiber_ids, window_manager=None):
    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        _sync_target_fibers(sync, vis_col, root, scene, depsgraph, bake, target_fiber_ids)
        _cleanup_stale_fiber_proxies(vis_col, root.name, {f.id for f in root.af_vcp_system.fibers})
        sync._sync_handles(root, scene, vis_col, {}, window_manager=window_manager)
        sync._apply_selection_highlight(root, scene)
    finally:
        sync._syncing = False


def _sync_target_fibers(sync, vis_col, root, scene, depsgraph, bake, target_fiber_ids):
    for fiber in _fibers_to_sync(root, target_fiber_ids):
        _sync_single_fiber(sync, vis_col, root, scene, depsgraph, fiber, bake)


def _find_fiber(root, fiber_id):
    return next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)


def _compute_attach_raw(sync, parent_obj, moved_world):
    local_pt = sync._nearest_parent_mesh_vertex_local_point(parent_obj, moved_world)
    return None if local_pt is None else encode_fiber_mesh_anchor(local_pt)


def _resolved_parent_obj(sync, scene, root, parent_id):
    return None if not parent_id else sync._get_scp_proxy(scene, root.name, parent_id)


def _resolved_attachment(sync, parent_obj, moved_world):
    return None if parent_obj is None else _compute_attach_raw(sync, parent_obj, moved_world)


def _resolved_conflict(fiber, aspect, current, incoming, payload):
    return str(resolve_conflict(entity_type="FIBER", entity_id=str(fiber.id or ""), aspect=aspect, source="blender_control", current=current, incoming=incoming, payload=payload) or "")


def _apply_attach_update(sync, fiber, changed_ids, setter, current, resolved):
    if current == resolved:
        return False
    setter(resolved)
    sync._set_fiber_prefer_bake(fiber, False)
    changed_ids.add(fiber.id)
    return True


def _update_endpoint_handle(sync, root, scene, obj, changed_ids):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    endpoint = obj.get("af_fiber_endpoint")
    if fiber is None:
        return False
    parent_id = fiber.a_parent_id if endpoint == "A" else fiber.b_parent_id
    raw = _resolved_attachment(sync, _resolved_parent_obj(sync, scene, root, parent_id), obj.location.copy())
    if raw is None:
        return False
    slot = "a_attach_param" if endpoint == "A" else "b_attach_param"
    current = str(getattr(fiber, slot) or "")
    incoming = str(raw or "")
    resolved = _resolved_conflict(fiber, f"attachment.{str(endpoint).lower()}.param", current, incoming, {"endpoint": str(endpoint or "")})
    return _apply_attach_update(sync, fiber, changed_ids, lambda value: setattr(fiber, slot, value), current, resolved)


def _update_touch_handle(sync, root, scene, obj, changed_ids):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    touch_index = int(obj.get("af_fiber_touch_index", -1))
    if fiber is None or touch_index < 0 or touch_index >= len(fiber.mid_touches):
        return False
    tp = fiber.mid_touches[touch_index]
    raw = _resolved_attachment(sync, _resolved_parent_obj(sync, scene, root, tp.parent_id), obj.location.copy())
    if raw is None:
        return False
    current = str(tp.attach_param or "")
    incoming = str(raw or "")
    resolved = _resolved_conflict(fiber, f"attachment.touch[{int(touch_index)}].param", current, incoming, {"touch_index": int(touch_index)})
    return _apply_attach_update(sync, fiber, changed_ids, lambda value: setattr(tp, "attach_param", value), current, resolved)


def _is_relevant_update_obj(sync, root, vis_col, obj):
    if not isinstance(obj, bpy.types.Object):
        return False
    if obj.get("af_root_name") != root.name:
        return False
    return vis_col.objects.get(obj.name) is not None


def _collect_changed_fiber_ids(sync, root, scene, depsgraph, vis_col, runtime):
    _ = runtime
    changed_fiber_ids = set()
    for upd in depsgraph.updates:
        obj = upd.id
        if not _is_relevant_update_obj(sync, root, vis_col, obj):
            continue
        if obj.get("af_fiber_endpoint_handle"):
            _update_endpoint_handle(sync, root, scene, obj, changed_fiber_ids)
        elif obj.get("af_fiber_touch_handle"):
            _update_touch_handle(sync, root, scene, obj, changed_fiber_ids)
    return changed_fiber_ids


def apply_fiber_control_update(sync, root, scene, obj, depsgraph):
    _ = depsgraph
    changed = set()
    if obj.get("af_fiber_endpoint_handle"):
        _update_endpoint_handle(sync, root, scene, obj, changed)
    elif obj.get("af_fiber_touch_handle"):
        _update_touch_handle(sync, root, scene, obj, changed)
    return next(iter(changed), None)


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return
    state = _depsgraph_sync_state(sync, scene)
    if state is None:
        return
    root, vis_col = state
    changed_fiber_ids = _collect_depsgraph_runtime(sync, root, vis_col, depsgraph)
    if changed_fiber_ids:
        _enqueue_fiber_runtime(root, scene, changed_fiber_ids)


def _depsgraph_sync_state(sync, scene):
    root = get_af_root(scene)
    vis_col = bpy.data.collections.get(sync.collection_name)
    return None if root is None or vis_col is None or not hasattr(root, "af_vcp_system") else (root, vis_col)


def _collect_depsgraph_runtime(sync, root, vis_col, depsgraph):
    sync._syncing = True
    try:
        return _depsgraph_changed_fibers(sync, root, vis_col, depsgraph)
    finally:
        sync._syncing = False


def _depsgraph_changed_fibers(sync, root, vis_col, depsgraph):
    changed = set()
    for upd in depsgraph.updates:
        _merge_changed_fibers(sync, root, vis_col, changed, upd.id)
    return changed


def _merge_changed_fibers(sync, root, vis_col, changed, obj):
    if not _is_relevant_update_obj(sync, root, vis_col, obj):
        return
    classified = classify_control_object(obj)
    if not classified or str(classified["control_type"]) not in ("FIBER_ENDPOINT", "FIBER_TOUCH"):
        return
    payload = dict(classified["payload"])
    payload["binding"] = classified.get("binding")
    if enqueue_control_intent(root, classified["control_type"], payload):
        changed |= set(classified["dirty_hints"].get("FIBER", set()) or set())


def _enqueue_fiber_runtime(root, scene, changed_fiber_ids):
    from .sync_runner import sync_from_dirty_hints

    sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty_hints_for("FIBER", changed_fiber_ids), source="depsgraph", event_type="TRANSFORM")
