import bpy

from ..deps.dirty_hints import dirty_hints_for
from ..deps.controls import classify_control_object, enqueue_control_intent
from ..deps.conflict_resolver import resolve_conflict
from ..scp_runtime.common import is_runtime_applied_matrix, mark_applied_matrix
from ..vcp.fiber_modes import is_loop_fiber, is_open_fiber
from ..vcp.fiber_node_attachment_codec import decode_node_attachments
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..vcp.runtime_state import fiber_eps_pen, fiber_invalid_reason, fiber_not_converged, fiber_route_mode
from ..utils import depsgraph_for_scene, get_af_root, scene_for_id
from .control_runtime import active_entity_id
from .fiber_attachment_transfer import capture_attachment_target, with_attachment_raw
from .fiber_sync_helpers import mark_fiber_output_stale, show_curve_preview
from .vcp_object_index import build_vcp_object_index
from ..vcp.free_path import fiber_geometry_point_count


def _iter_endpoints(fiber):
    return (
        ("A", fiber.a_parent_id, fiber.a_attach_param),
        ("B", fiber.b_parent_id, fiber.b_attach_param),
    )


def _place_handle_world(handle, point):
    matrix = handle.matrix_world.copy()
    matrix.translation = point
    handle.matrix_world = matrix
    mark_applied_matrix(handle)


def _sync_endpoint_handle(sync, vis_col, root, scene, runtime_registry, fiber, endpoint, parent_id, raw, window_manager=None):
    h = sync._find_endpoint_handle(vis_col, root.name, fiber.id, endpoint)
    if h is None:
        h = sync._create_endpoint_handle(vis_col, root, fiber.id, endpoint)
    w = sync._endpoint_world(root, scene, runtime_registry, parent_id, raw)
    if w is not None:
        _place_handle_world(h, w)
        sync._set_helper_screen_size(h, px=14.0, window_manager=window_manager)


def _sync_touch_handle(sync, vis_col, root, scene, runtime_registry, fiber, index, touch, window_manager=None):
    h = sync._find_touch_handle(vis_col, root.name, fiber.id, index)
    if h is None:
        h = sync._create_touch_handle(vis_col, root, fiber.id, index)
    w = sync._endpoint_world(root, scene, runtime_registry, touch.parent_id, touch.attach_param)
    if w is not None:
        _place_handle_world(h, w)
        sync._set_helper_screen_size(h, px=12.0, window_manager=window_manager)


def _sync_loop_anchor_handle(sync, vis_col, root, scene, runtime_registry, fiber, index, anchor, window_manager=None):
    h = sync._find_loop_anchor_handle(vis_col, root.name, fiber.id, index)
    if h is None:
        h = sync._create_loop_anchor_handle(vis_col, root, fiber.id, index)
    w = sync._endpoint_world(root, scene, runtime_registry, anchor.parent_id, anchor.attach_param)
    if w is not None:
        _place_handle_world(h, w)
        sync._set_helper_screen_size(h, px=13.0, window_manager=window_manager)


def _cleanup_stale_handles(vis_col, root_name, live_endpoint_keys, live_touch_keys, live_loop_keys):
    for obj in list(vis_col.objects):
        if _safe_get(obj, "af_fiber_endpoint_handle") and _safe_get(obj, "af_root_name") == root_name:
            key = (_safe_get(obj, "af_fiber_id"), _safe_get(obj, "af_fiber_endpoint"))
            if key not in live_endpoint_keys:
                bpy.data.objects.remove(obj, do_unlink=True)
        if _safe_get(obj, "af_fiber_touch_handle") and _safe_get(obj, "af_root_name") == root_name:
            key = (_safe_get(obj, "af_fiber_id"), int(_safe_get(obj, "af_fiber_touch_index", -1)))
            if key not in live_touch_keys:
                bpy.data.objects.remove(obj, do_unlink=True)
        if _safe_get(obj, "af_fiber_loop_anchor_handle") and _safe_get(obj, "af_root_name") == root_name:
            key = (_safe_get(obj, "af_fiber_id"), int(_safe_get(obj, "af_fiber_loop_anchor_index", -1)))
            if key not in live_loop_keys:
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
    live_loop_keys = set()
    fiber = _active_fiber(root, scene)
    if fiber is not None and is_open_fiber(fiber):
        _sync_fiber_handles(sync, root, scene, vis_col, runtime_registry, fiber, live_endpoint_keys, live_touch_keys, window_manager)
    if fiber is not None and is_loop_fiber(fiber):
        _sync_loop_handles(sync, root, scene, vis_col, runtime_registry, fiber, live_loop_keys, window_manager)
    _cleanup_stale_handles(vis_col, root.name, live_endpoint_keys, live_touch_keys, live_loop_keys)


def _sync_fiber_handles(sync, root, scene, vis_col, runtime_registry, fiber, live_endpoint_keys, live_touch_keys, window_manager=None):
    for endpoint, pid, raw in _iter_endpoints(fiber):
        live_endpoint_keys.add((fiber.id, endpoint))
        _sync_endpoint_handle(sync, vis_col, root, scene, runtime_registry, fiber, endpoint, pid, raw, window_manager)
    for i, tp in enumerate(fiber.mid_touches):
        live_touch_keys.add((fiber.id, i))
        _sync_touch_handle(sync, vis_col, root, scene, runtime_registry, fiber, i, tp, window_manager)


def _sync_loop_handles(sync, root, scene, vis_col, runtime_registry, fiber, live_loop_keys, window_manager=None):
    for i, anchor in enumerate(getattr(fiber, "loop_anchors", ())):
        live_loop_keys.add((fiber.id, i))
        _sync_loop_anchor_handle(sync, vis_col, root, scene, runtime_registry, fiber, i, anchor, window_manager)


def apply_selection_highlight(sync, root, scene, objects=None):
    active_id = root.af_vcp_system.active_vcp_id
    active_type = root.af_vcp_system.active_vcp_type
    for obj in scene.objects if objects is None else objects:
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
    return sorted(tuple(fibers or ()), key=lambda fiber: str(fiber.id or ""))


def _sync_single_fiber(sync, vis_col, root, scene, depsgraph, fiber, bake):
    _ = vis_col, depsgraph
    from .fiber_refinement import request_fiber_refinement
    if sync._fiber_prefer_bake(fiber):
        sync._set_fiber_prefer_bake(fiber, False)
    quality = "FINAL" if bake else "INTERACTIVE"
    return request_fiber_refinement(root, scene, fiber, show_preview=True, quality=quality)


def _sync_commit_allowed(fiber, points):
    if fiber_invalid_reason(fiber) or len(points) != int(fiber.node_count):
        return False
    if _failed_planner_preview(fiber):
        return False
    if not all(all(_finite(value) for value in point) for point in points):
        return False
    if _effective_solver_version(fiber) >= 2:
        return float(fiber_eps_pen(fiber)) < 1.0e-5 and not fiber_not_converged(fiber)
    if not _requires_collision_truth(fiber):
        return True
    return float(fiber_eps_pen(fiber)) < 1.0e-5


def _failed_planner_preview(fiber):
    return bool(getattr(fiber, "preview_planner_route", False) and
                fiber_route_mode(fiber) == "LOCAL_FALLBACK")


def _finite(value):
    from math import isfinite
    return isfinite(float(value))


def _requires_collision_truth(fiber):
    return bool(getattr(fiber, "use_segment_collisions", False) or
                len(tuple(getattr(fiber, "mid_touches", ()) or ())))


def _effective_solver_version(fiber):
    try:
        pending = int(fiber.get("af_pending_solver_version", 0) or 0)
    except Exception:
        pending = 0
    return max(int(getattr(fiber, "solver_version", 1) or 1), pending)


def _retain_or_clear_failed(sync, root, scene, fiber, obj, points):
    preview = (len(points) >= 2 and bool(getattr(fiber, "preview_planner_route", False))
               and fiber_route_mode(fiber) != "LOCAL_FALLBACK")
    if preview:
        show_curve_preview(obj, points, fiber.thickness, cyclic=sync._fiber_cyclic(fiber))
        mark_fiber_output_stale(scene, root.name, fiber.id)
    elif obj.get("af_fiber_points_world"):
        mark_fiber_output_stale(scene, root.name, fiber.id)
    else:
        sync._clear_curve_points(obj)


def apply_fiber_points(sync, root, scene, fiber, points, bake=False, commit=True):
    vis_col = sync._get_vis_collection(scene)
    if vis_col is None or fiber is None or len(tuple(points or ())) < 2:
        return None
    owned = _prepare_point_index(sync, vis_col, root.name)
    try:
        obj = sync._find_fiber_proxy(vis_col, root.name, fiber.id)
        obj = obj or sync._create_fiber_proxy(vis_col, root, fiber.id)
        sync._update_curve_points(obj, points, fiber.thickness, bake=bake,
                                  cyclic=sync._fiber_cyclic(fiber), commit=commit)
        return obj
    finally:
        if owned: sync._object_index = None; sync._object_index_key = None


def _prepare_point_index(sync, vis_col, root_name):
    key = (vis_col.name, root_name); batched = bool(getattr(sync, "_point_batch_depth", 0))
    if sync._object_index is not None and (not batched or sync._object_index_key == key): return False
    sync._object_index = build_vcp_object_index(vis_col, root_name)
    sync._object_index_key = key; return not batched


def _cleanup_stale_fiber_proxies(vis_col, root_name, live_ids):
    for obj in list(vis_col.objects):
        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") not in live_ids:
            bpy.data.objects.remove(obj, do_unlink=True)


def _sync_inputs(root, scene):
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    depsgraph = depsgraph_for_scene(scene)
    return root, scene, depsgraph


def sync_root_to_scene(sync, root=None, scene=None, bake=False, target_fiber_ids=None, window_manager=None, drain=True):
    if sync._syncing:
        return
    state = _scene_sync_state(root, scene)
    if state is None:
        return
    _run_scene_sync(sync, *state, bake, target_fiber_ids, window_manager, drain)


def refresh_selection(sync, root=None, scene=None, window_manager=None, fiber_ids=None, sync_handles=False):
    if sync._syncing:
        return
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    if root is None or scene is None:
        return
    _run_selection_refresh(sync, root, scene, window_manager, fiber_ids, sync_handles)


def refresh_propagated_handles(sync, root, scene, points_by_id, fiber_ids):
    fiber = _active_fiber(root, scene); affected = set(fiber_ids or ())
    if fiber is None or str(fiber.id) not in affected: return True
    points = tuple(dict(points_by_id or {}).get(str(fiber.id), ()))
    if len(points) != fiber_geometry_point_count(fiber): return False
    payload = decode_node_attachments(fiber.node_attachments_json)
    indices = _propagated_pin_indices(fiber, payload)
    if indices is None: return False
    vis_col = sync._get_vis_collection(scene); index = build_vcp_object_index(vis_col, root.name)
    return _place_propagated_handles(index, fiber, points, indices)


def _propagated_pin_indices(fiber, payload):
    if payload is None or payload.point_count != fiber_geometry_point_count(fiber): return None
    bindings = _propagated_bindings(fiber)
    if is_loop_fiber(fiber): return _ordered_matches(payload.nodes, bindings, 0, len(payload.nodes))
    return _open_matches(payload.nodes, bindings)


def _propagated_bindings(fiber):
    if is_loop_fiber(fiber):
        return tuple((row.parent_id, row.attach_param) for row in fiber.loop_anchors)
    values = [(fiber.a_parent_id, fiber.a_attach_param)]
    values.extend((row.parent_id, row.attach_param) for row in fiber.mid_touches)
    values.append((fiber.b_parent_id, fiber.b_attach_param)); return tuple(values)


def _open_matches(nodes, bindings):
    if len(nodes) < 2 or len(bindings) < 2: return None
    if not _binding_matches(nodes[0], bindings[0]): return None
    if not _binding_matches(nodes[-1], bindings[-1]): return None
    middle = _ordered_matches(nodes, bindings[1:-1], 1, len(nodes) - 1)
    return None if middle is None else (0, *middle, len(nodes) - 1)


def _ordered_matches(nodes, bindings, start, stop):
    indices, cursor = [], int(start)
    for binding in bindings:
        match = next((i for i in range(cursor, stop) if _binding_matches(nodes[i], binding)), None)
        if match is None: return None
        indices.append(match); cursor = match + 1
    return tuple(indices)


def _binding_matches(node, binding):
    return node.target_id == str(binding[0] or "") and node.attach_raw == str(binding[1] or "")


def _place_propagated_handles(index, fiber, points, indices):
    handles = _propagated_handle_rows(index, fiber)
    if len(handles) != len(indices) or any(handle is None for handle in handles): return False
    for handle, point_index in zip(handles, indices): _place_handle_world(handle, points[point_index])
    return True


def _propagated_handle_rows(index, fiber):
    fid = str(fiber.id)
    if is_loop_fiber(fiber):
        return tuple(index["loop"].get((fid, i)) for i in range(len(fiber.loop_anchors)))
    values = [index["endpoint"].get((fid, "A"))]
    values.extend(index["touch"].get((fid, i)) for i in range(len(fiber.mid_touches)))
    values.append(index["endpoint"].get((fid, "B"))); return tuple(values)


def refresh_display(sync, root=None, scene=None, target_fiber_ids=None):
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    if sync._syncing or root is None or scene is None:
        return
    vis_col = sync._get_vis_collection(scene)
    index = build_vcp_object_index(vis_col, root.name)
    for fiber in _fibers_to_sync(root, target_fiber_ids):
        _refresh_fiber_style(sync, index, fiber)


def _refresh_fiber_style(sync, index, fiber):
    for obj in (index["fiber"].get(fiber.id), index["fiber_mirror"].get(fiber.id)):
        if obj is not None:
            sync._update_curve_style(obj, fiber.thickness)


def _scene_sync_state(root, scene):
    root, scene, depsgraph = _sync_inputs(root, scene)
    return None if root is None or depsgraph is None or not hasattr(root, "af_vcp_system") else (root, scene, depsgraph)


def _run_scene_sync(sync, root, scene, depsgraph, bake, target_fiber_ids, window_manager=None, drain=True):
    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        sync._object_index = build_vcp_object_index(vis_col, root.name)
        _sync_target_fibers(sync, vis_col, root, scene, depsgraph, bake, target_fiber_ids, drain)
        _cleanup_stale_fiber_proxies(vis_col, root.name, {f.id for f in root.af_vcp_system.fibers})
        sync._sync_handles(root, scene, vis_col, {}, window_manager=window_manager)
        sync._apply_selection_highlight(root, scene)
    finally:
        sync._object_index = None
        sync._syncing = False


def _run_selection_refresh(sync, root, scene, window_manager=None, fiber_ids=None, sync_handles=False):
    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        sync._object_index = build_vcp_object_index(vis_col, root.name)
        if sync_handles:
            sync._sync_handles(root, scene, vis_col, {}, window_manager=window_manager)
        objects = _selection_objects(sync._object_index, fiber_ids)
        apply_selection_highlight(sync, root, scene, objects)
    finally:
        sync._object_index = None
        sync._syncing = False


def _selection_objects(index, fiber_ids):
    if fiber_ids is None:
        return None
    ids = set(fiber_ids or ())
    return [obj for key in ("fiber", "fiber_mirror") for fid, obj in index[key].items() if fid in ids]


def _sync_target_fibers(sync, vis_col, root, scene, depsgraph, bake, target_fiber_ids, drain=True):
    for fiber in _fibers_to_sync(root, target_fiber_ids):
        _sync_single_fiber(sync, vis_col, root, scene, depsgraph, fiber, bake)
    if drain:
        from .fiber_refinement import drain_fiber_refinements
        drain_fiber_refinements()


def _find_fiber(root, fiber_id):
    return next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)


def _resolved_conflict(fiber, aspect, current, incoming, payload):
    return str(resolve_conflict(entity_type="FIBER", entity_id=str(fiber.id or ""), aspect=aspect, source="blender_control", current=current, incoming=incoming, payload=payload) or "")


def _resolved_attachment(fiber, aspect, owner, raw, target, payload):
    incoming_owner = str(target.owner_id or ""); owner = str(owner or "")
    owner_aspect = aspect.rsplit(".", 1)[0] + ".owner"
    resolved_owner = owner if incoming_owner == owner else _resolved_conflict(
        fiber, owner_aspect, owner, incoming_owner, payload)
    if resolved_owner != incoming_owner: return None
    resolved_raw = _resolved_conflict(fiber, aspect, raw, target.raw, payload)
    return with_attachment_raw(target, resolved_raw)


def _apply_attachment_target(sync, fiber, changed_ids, setters, owner, raw, target):
    if target is None: return False
    if (str(owner or ""), str(raw or "")) == (target.owner_id, target.raw): return False
    before = _shared_bindings(fiber)
    with suppress_vcp_prop_updates():
        setters[0](target.owner_id); setters[1](target.raw)
    _invalidate_shared_edit(sync, fiber, before, changed_ids)
    return True


def _shared_bindings(fiber):
    from ..vcp.shared_point_storage import slots, point_record
    points = [point_record(owner, slot) for owner, slot, _ in slots(fiber)]
    return {p.id: (p.parent_id, p.attach_param, p.normal_offset) for p in points if p is not None}


def _invalidate_shared_edit(sync, fiber, before, changed_ids):
    from ..vcp.shared_point_storage import point_users
    after = _shared_bindings(fiber)
    users = {fiber.id: fiber}
    for key, value in after.items():
        if before.get(key) != value:
            users.update({f.id: f for f, _, _ in point_users(fiber.id_data, key)})
    for f in users.values():
        sync.clear_solver_cache(f.id)
        sync._set_fiber_prefer_bake(f, False)
        changed_ids.add(f.id)


def _changed_attachment(sync, root, scene, parent_id, obj, depsgraph, fiber, raw, offset=0., point_id=''):
    target = capture_attachment_target(sync, root, scene, parent_id, obj.location.copy(), depsgraph,
                                       _point_snap_radius(root, point_id, fiber.collision_radius), offset)
    if target is None: _restore_pin_handle(root, scene, obj, parent_id, raw, depsgraph)
    return target


def _point_snap_radius(root, point_id, fallback):
    from ..vcp.shared_point_storage import point_users
    users = point_users(root, point_id) if point_id else ()
    return max((float(f.collision_radius) for f, _, _ in users), default=float(fallback))


def _endpoint_target(sync, root, scene, obj, depsgraph, fiber, endpoint):
    from ..vcp.shared_point_storage import endpoint_record
    side = str(endpoint).lower()
    point = endpoint_record(fiber, side)
    return _changed_attachment(sync, root, scene, point.parent_id, obj, depsgraph, fiber,
                               point.attach_param, point.normal_offset, getattr(fiber, side+'_point_id', ''))


def _restore_pin_handle(root, scene, obj, owner, raw, depsgraph):
    from ..vcp.attachment_backend import attachment_runtime, resolve_attachment_world
    point = resolve_attachment_world(root, scene, owner, raw, attachment_runtime(scene, depsgraph))
    if point is not None: _place_handle_world(obj, point)


def _apply_handle_target(sync, fiber, changed_ids, setters, owner, raw, target, context):
    changed = _apply_attachment_target(sync, fiber, changed_ids, setters, owner, raw, target)
    if context is not None:
        root, scene, obj, depsgraph = context
        final_owner, final_raw = (target.owner_id, target.raw) if changed else (owner, raw)
        _restore_pin_handle(root, scene, obj, final_owner, final_raw, depsgraph)
    return changed


def _endpoint_parts(fiber, endpoint):
    parent_id = fiber.a_parent_id if endpoint == "A" else fiber.b_parent_id
    slot = "a_attach_param" if endpoint == "A" else "b_attach_param"
    return parent_id, str(getattr(fiber, slot) or ""), slot


def _update_endpoint_handle(sync, root, scene, obj, changed_ids, depsgraph=None):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    endpoint = obj.get("af_fiber_endpoint")
    if fiber is None:
        return False
    parent_id, current, slot = _endpoint_parts(fiber, endpoint)
    target = _endpoint_target(sync, root, scene, obj, depsgraph, fiber, endpoint)
    if target is None: return False
    aspect = f"attachment.{str(endpoint).lower()}.param"
    payload = {"endpoint": str(endpoint or "")}
    target = _resolved_attachment(fiber, aspect, parent_id, current, target, payload)
    setters = (lambda value: setattr(fiber, f"{str(endpoint).lower()}_parent_id", value),
               lambda value: setattr(fiber, slot, value))
    return _apply_handle_target(sync, fiber, changed_ids, setters, parent_id, current, target, (root, scene, obj, depsgraph))


def _touch_at(fiber, touch_index):
    if fiber is None or touch_index < 0 or touch_index >= len(fiber.mid_touches):
        return None
    return fiber.mid_touches[touch_index]


def _update_touch_handle(sync, root, scene, obj, changed_ids, depsgraph=None):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    touch_index = int(obj.get("af_fiber_touch_index", -1))
    tp = _touch_at(fiber, touch_index)
    if tp is None:
        return False
    current = str(tp.attach_param or "")
    target = _changed_attachment(sync, root, scene, tp.parent_id, obj, depsgraph, fiber, current, tp.normal_offset, getattr(tp, 'point_id', ''))
    if target is None: return False
    aspect = f"attachment.touch[{int(touch_index)}].param"
    target = _resolved_attachment(fiber, aspect, tp.parent_id, current, target,
                                  {"touch_index": int(touch_index)})
    setters = (lambda value: setattr(tp, "parent_id", value),
               lambda value: setattr(tp, "attach_param", value))
    return _apply_handle_target(sync, fiber, changed_ids, setters, tp.parent_id, current, target, (root, scene, obj, depsgraph))


def _update_loop_anchor_handle(sync, root, scene, obj, changed_ids, depsgraph=None):
    fiber = _find_fiber(root, obj.get("af_fiber_id"))
    anchor_index = int(obj.get("af_fiber_loop_anchor_index", -1))
    if fiber is None or anchor_index < 0 or anchor_index >= len(fiber.loop_anchors):
        return False
    anchor = fiber.loop_anchors[anchor_index]
    target = _changed_attachment(sync, root, scene, anchor.parent_id, obj, depsgraph, fiber, anchor.attach_param)
    return _apply_loop_anchor_target(sync, fiber, anchor, anchor_index, target, changed_ids, (root, scene, obj, depsgraph))


def _apply_loop_anchor_target(sync, fiber, anchor, index, target, changed_ids, context=None):
    if target is None: return False
    current = str(anchor.attach_param or ""); payload = {"loop_anchor_index": int(index)}
    aspect = f"attachment.loop_anchor[{int(index)}].param"
    target = _resolved_attachment(fiber, aspect, anchor.parent_id, current, target, payload)
    setters = (lambda value: setattr(anchor, "parent_id", value),
               lambda value: setattr(anchor, "attach_param", value))
    return _apply_handle_target(sync, fiber, changed_ids, setters, anchor.parent_id, current, target, context)


def _is_relevant_update_obj(sync, root, vis_col, obj, object_names=None):
    if not isinstance(obj, bpy.types.Object):
        return False
    if obj.get("af_root_name") != root.name:
        return False
    if object_names is not None:
        return obj.name in object_names
    return vis_col.objects.get(obj.name) is not None


def _collect_changed_fiber_ids(sync, root, scene, depsgraph, vis_col, runtime):
    _ = runtime
    changed_fiber_ids = set()
    for upd in depsgraph.updates:
        obj = upd.id
        if not _is_relevant_update_obj(sync, root, vis_col, obj):
            continue
        if obj.get("af_fiber_endpoint_handle"):
            _update_endpoint_handle(sync, root, scene, obj, changed_fiber_ids, depsgraph)
        elif obj.get("af_fiber_touch_handle"):
            _update_touch_handle(sync, root, scene, obj, changed_fiber_ids, depsgraph)
        elif obj.get("af_fiber_loop_anchor_handle"):
            _update_loop_anchor_handle(sync, root, scene, obj, changed_fiber_ids, depsgraph)
    return changed_fiber_ids


def apply_fiber_control_update(sync, root, scene, obj, depsgraph):
    changed = set()
    if obj.get("af_fiber_endpoint_handle"):
        _update_endpoint_handle(sync, root, scene, obj, changed, depsgraph)
    elif obj.get("af_fiber_touch_handle"):
        _update_touch_handle(sync, root, scene, obj, changed, depsgraph)
    elif obj.get("af_fiber_loop_anchor_handle"):
        _update_loop_anchor_handle(sync, root, scene, obj, changed, depsgraph)
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
    # Evaluated IDs can be distinct objects; collection lookup has name semantics.
    object_names = {obj.name for obj in vis_col.objects}
    for upd in depsgraph.updates:
        _merge_changed_fibers(sync, root, vis_col, changed, upd.id, object_names)
    return changed


def _merge_changed_fibers(sync, root, vis_col, changed, obj, object_names=None):
    if not _is_relevant_update_obj(sync, root, vis_col, obj, object_names):
        return
    if is_runtime_applied_matrix(obj):
        return
    classified = classify_control_object(obj)
    if not classified or str(classified["control_type"]) not in ("FIBER_ENDPOINT", "FIBER_TOUCH", "FIBER_LOOP_ANCHOR"):
        return
    payload = dict(classified["payload"])
    payload["binding"] = classified.get("binding")
    if enqueue_control_intent(root, classified["control_type"], payload):
        mark_applied_matrix(obj)
        changed |= set(classified["dirty_hints"].get("FIBER", set()) or set())


def _enqueue_fiber_runtime(root, scene, changed_fiber_ids):
    from .sync_runner import schedule_sync_from_dirty_hints

    aspects = {"FIBER": {"ATTACHMENT"}}
    schedule_sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty_hints_for("FIBER", changed_fiber_ids),
                                   source="depsgraph", event_type="FIBER_UPDATE", dirty_aspects=aspects, quality="INTERACTIVE")
