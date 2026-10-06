import bpy
import hashlib
import json
from math import isfinite
from mathutils import Vector
from bpy_extras import view3d_utils

from ..deps.control_lifecycle import mark_dynamic_control_object
from ..deps.runtime_trace import telemetry_count
from ..scp_runtime.object_colors import apply_object_color
from ..attachment_codec import fiber_attach_signature
from ..scp_proxy.signature import mesh_topology_signature
from ..perf_trace import perf_count, perf_time, perf_timer
from ..utils import depsgraph_for_scene, scene_cache_get, scene_cache_set, scene_for_id
from ..scp_runtime.common import find_geometry_scp_obj
from ..vcp.attachment_backend import resolve_attachment_normal, resolve_attachment_world


def get_vis_collection(scene, collection_name):
    col = scene.collection.children.get(collection_name)
    if col is None:
        col = bpy.data.collections.new(collection_name)
        scene.collection.children.link(col)
    return col


def find_fiber_proxy(vis_col, root_name, fiber_id, index=None):
    indexed = _indexed(index, "fiber", str(fiber_id or ""))
    if indexed is not None:
        return indexed
    for obj in vis_col.objects:
        if (
            obj.get("af_fiber_proxy")
            and not obj.get("af_fiber_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_fiber_id") == fiber_id
        ):
            return obj
    return None


def _indexed(index, bucket, key):
    return None if index is None else dict(index.get(bucket, {})).get(key)


def _find_with(objects, predicate):
    return next((obj for obj in objects if predicate(obj)), None)


def _endpoint_match(obj, root_name, fiber_id, endpoint):
    return (
        obj.get("af_fiber_endpoint_handle")
        and obj.get("af_root_name") == root_name
        and obj.get("af_fiber_id") == fiber_id
        and obj.get("af_fiber_endpoint") == endpoint
    )


def find_endpoint_handle(vis_col, root_name, fiber_id, endpoint, index=None):
    indexed = _indexed(index, "endpoint", (str(fiber_id or ""), str(endpoint or "")))
    if indexed is not None:
        return indexed
    return _find_with(
        vis_col.objects,
        lambda obj: _endpoint_match(obj, root_name, fiber_id, endpoint),
    ) or _find_with(
        bpy.data.objects,
        lambda obj: _endpoint_match(obj, root_name, fiber_id, endpoint),
    )


def _touch_match(obj, root_name, fiber_id, touch_index):
    return (
        obj.get("af_fiber_touch_handle")
        and obj.get("af_root_name") == root_name
        and obj.get("af_fiber_id") == fiber_id
        and int(obj.get("af_fiber_touch_index", -1)) == int(touch_index)
    )


def _loop_anchor_match(obj, root_name, fiber_id, anchor_index):
    return (
        obj.get("af_fiber_loop_anchor_handle")
        and obj.get("af_root_name") == root_name
        and obj.get("af_fiber_id") == fiber_id
        and int(obj.get("af_fiber_loop_anchor_index", -1)) == int(anchor_index)
    )


def find_touch_handle(vis_col, root_name, fiber_id, touch_index, index=None):
    indexed = _indexed(index, "touch", (str(fiber_id or ""), int(touch_index)))
    if indexed is not None:
        return indexed
    return _find_with(
        vis_col.objects,
        lambda obj: _touch_match(obj, root_name, fiber_id, touch_index),
    ) or _find_with(
        bpy.data.objects,
        lambda obj: _touch_match(obj, root_name, fiber_id, touch_index),
    )


def find_loop_anchor_handle(vis_col, root_name, fiber_id, anchor_index, index=None):
    indexed = _indexed(index, "loop", (str(fiber_id or ""), int(anchor_index)))
    if indexed is not None:
        return indexed
    return _find_with(
        vis_col.objects,
        lambda obj: _loop_anchor_match(obj, root_name, fiber_id, anchor_index),
    ) or _find_with(
        bpy.data.objects,
        lambda obj: _loop_anchor_match(obj, root_name, fiber_id, anchor_index),
    )


def create_endpoint_handle(vis_col, root, fiber_id, endpoint):
    obj = bpy.data.objects.new(f"AF_{fiber_id}_{endpoint}", None)
    mark_endpoint_handle(obj, root, fiber_id, endpoint, apply_visual_defaults=True)
    mark_dynamic_control_object(obj)
    vis_col.objects.link(obj)
    return obj


def create_touch_handle(vis_col, root, fiber_id, touch_index):
    obj = bpy.data.objects.new(f"AF_{fiber_id}_T{touch_index}", None)
    mark_touch_handle(obj, root, fiber_id, touch_index, apply_visual_defaults=True)
    mark_dynamic_control_object(obj)
    vis_col.objects.link(obj)
    return obj


def create_loop_anchor_handle(vis_col, root, fiber_id, anchor_index):
    obj = bpy.data.objects.new(f"AF_{fiber_id}_L{anchor_index}", None)
    mark_loop_anchor_handle(obj, root, fiber_id, anchor_index, apply_visual_defaults=True)
    mark_dynamic_control_object(obj)
    vis_col.objects.link(obj)
    return obj


def mark_endpoint_handle(obj, root, fiber_id, endpoint, apply_visual_defaults=False):
    if obj is None:
        return None
    if bool(apply_visual_defaults):
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.035
        obj.show_in_front = True
        obj.hide_render = True
    obj["af_fiber_endpoint_handle"] = True
    obj["af_root_name"] = root.name
    obj["af_fiber_id"] = fiber_id
    obj["af_fiber_endpoint"] = endpoint
    return obj


def mark_touch_handle(obj, root, fiber_id, touch_index, apply_visual_defaults=False):
    if obj is None:
        return None
    if bool(apply_visual_defaults):
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 0.03
        obj.show_in_front = True
        obj.hide_render = True
    obj["af_fiber_touch_handle"] = True
    obj["af_root_name"] = root.name
    obj["af_fiber_id"] = fiber_id
    obj["af_fiber_touch_index"] = int(touch_index)
    return obj


def mark_loop_anchor_handle(obj, root, fiber_id, anchor_index, apply_visual_defaults=False):
    if obj is None:
        return None
    if bool(apply_visual_defaults):
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = 0.034
        obj.show_in_front = True
        obj.hide_render = True
    obj["af_fiber_loop_anchor_handle"] = True
    obj["af_root_name"] = root.name
    obj["af_fiber_id"] = fiber_id
    obj["af_fiber_loop_anchor_index"] = int(anchor_index)
    return obj


def ensure_fiber_material(obj):
    if obj.data is None or not hasattr(obj.data, "materials"):
        return None
    if obj.data.materials and obj.data.materials[0]:
        return obj.data.materials[0]
    mat = bpy.data.materials.get(f"AF_FIBER_MAT_{obj.get('af_fiber_id', obj.name)}")
    if mat is None:
        mat = bpy.data.materials.new(f"AF_FIBER_MAT_{obj.get('af_fiber_id', obj.name)}")
        mat.use_nodes = False
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat


def set_fiber_color(obj, color):
    mat = ensure_fiber_material(obj)
    apply_object_color(obj, color)
    if mat:
        mat.diffuse_color = color


def create_fiber_proxy(vis_col, root, fiber_id, default_color):
    curve = bpy.data.curves.new(f"AF_{fiber_id}_curve", type="CURVE")
    curve.dimensions = "3D"
    obj = bpy.data.objects.new(f"AF_{fiber_id}", curve)
    obj["af_fiber_proxy"] = True
    obj["af_root_name"] = root.name
    obj["af_fiber_id"] = fiber_id
    obj["af_fiber_base_color"] = list(default_color)
    vis_col.objects.link(obj)
    set_fiber_color(obj, default_color)
    return obj


def _fiber_points_key(root_name, fiber_id):
    return f"fiber_points:{str(root_name or '')}:{str(fiber_id or '')}"


def cached_fiber_points(scene, root_name, fiber_id, index=None):
    proxy = _fiber_proxy(scene, root_name, fiber_id) if index is None else index.get('fiber', {}).get(str(fiber_id))
    if proxy is not None and proxy.get("af_fiber_output_state") == "STALE":
        return None
    raw = scene_cache_get(scene, _fiber_points_key(root_name, fiber_id))
    if raw is None:
        raw = _hydrate_fiber_points(scene, proxy, root_name, fiber_id)
    return None if raw is None else [Vector(item) for item in raw]


def persisted_fiber_points(scene, root_name, fiber_id):
    proxy = _fiber_proxy(scene, root_name, fiber_id)
    raw = _decode_fiber_points(None if proxy is None else proxy.get("af_fiber_points_world", ""))
    return None if raw is None else [Vector(item) for item in raw]


def mark_fiber_output_stale(scene, root_name, fiber_id):
    proxy = _fiber_proxy(scene, root_name, fiber_id)
    if proxy is not None and proxy.get("af_fiber_points_world"):
        proxy["af_fiber_output_state"] = "STALE"
    return proxy


def mark_fiber_output_current(obj, increment=True):
    if obj is None:
        return
    obj["af_fiber_output_state"] = "CURRENT"
    if increment:
        obj["af_fiber_output_generation"] = int(obj.get("af_fiber_output_generation", 0)) + 1


def _fiber_proxy(scene, root_name, fiber_id):
    objects = () if scene is None else tuple(getattr(scene, "objects", ()) or ())
    return next((obj for obj in objects if _fiber_proxy_matches(obj, root_name, fiber_id)), None)


def _fiber_proxy_matches(obj, root_name, fiber_id):
    return bool(obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy")
                and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == fiber_id)


def _hydrate_fiber_points(scene, proxy, root_name, fiber_id):
    raw = _decode_fiber_points(None if proxy is None else proxy.get("af_fiber_points_world", ""))
    if raw is not None:
        scene_cache_set(scene, _fiber_points_key(root_name, fiber_id), raw)
    return raw


def _decode_fiber_points(raw):
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
        points = tuple(tuple(float(value) for value in row[:3]) for row in rows)
        return points if all(len(row) == 3 and all(isfinite(v) for v in row) for row in points) else None
    except Exception:
        return None


def _store_fiber_points(obj, points):
    scene = scene_for_id(obj)
    key = _fiber_points_key(obj.get("af_root_name"), obj.get("af_fiber_id"))
    scene_cache_set(scene, key, tuple((float(p.x), float(p.y), float(p.z)) for p in points))


def _clear_fiber_points_cache(obj):
    scene = scene_for_id(obj)
    key = _fiber_points_key(obj.get("af_root_name"), obj.get("af_fiber_id"))
    scene_cache_set(scene, key, ())


def _curve_signature(points, thickness, bake, cyclic):
    h = hashlib.sha1(f"{len(points)}|{float(thickness):.8f}|{int(bake)}|{int(cyclic)}".encode())
    for p in points:
        h.update(f"|{float(p.x):.6f},{float(p.y):.6f},{float(p.z):.6f}".encode())
    return h.hexdigest()


def _flat_curve_points(points):
    return [value for p in points for value in (float(p.x), float(p.y), float(p.z), 1.0)]


def _clear_splines(curve):
    while curve.splines:
        curve.splines.remove(curve.splines[0])


def _write_curve_spline(curve, points, cyclic):
    _clear_splines(curve)
    spline = curve.splines.new(type="POLY")
    spline.points.add(len(points) - 1)
    spline.points.foreach_set("co", _flat_curve_points(points))
    spline.use_cyclic_u = bool(cyclic and len(points) > 2)


def update_curve_points(obj, points, thickness, bake=False, cyclic=False, commit=True):
    if not commit:
        _write_curve_preview(obj, points, thickness, cyclic)
        return
    scene, start = scene_for_id(obj), perf_timer()
    signature = _curve_signature(points, thickness, bake, cyclic)
    try:
        if _reuse_curve_payload(obj, points, signature, scene):
            return
        _store_fiber_points(obj, points)
        mark_fiber_output_current(obj)
        _write_curve_payload(obj, points, thickness, bake, cyclic, signature)
    finally:
        perf_time(scene, "fiber_curve_update", start)


def _reuse_curve_payload(obj, points, signature, scene):
    if obj.get("af_fiber_points_signature") != signature:
        return False
    _store_fiber_points(obj, points)
    mark_fiber_output_current(obj, increment=False)
    perf_count(scene, "curve_rewrite_skipped")
    return True


def _write_curve_preview(obj, points, thickness, cyclic):
    from .mirror_objects import detach_shared_mirrors
    detach_shared_mirrors(obj)
    telemetry_count("fiber_preview_writes")
    _write_curve_spline(obj.data, points, cyclic)
    update_curve_style(obj, thickness)


def show_curve_preview(obj, points, thickness, cyclic=False):
    _write_curve_preview(obj, points, thickness, cyclic)


def update_curve_style(obj, thickness):
    if obj is None or getattr(obj, "type", "") != "CURVE" or obj.data is None:
        return False
    value = max(0.0, float(thickness))
    if abs(float(obj.data.bevel_depth) - value) <= 1.0e-12:
        return False
    obj.data.bevel_depth = value
    return True


def _write_curve_payload(obj, points, thickness, bake, cyclic, signature):
    telemetry_count("fiber_writes")
    curve = obj.data
    _write_curve_spline(curve, points, cyclic)
    curve.bevel_depth = max(0.0, float(thickness))
    curve.fill_mode = "FULL"
    obj["af_fiber_points_world"] = json.dumps([[float(p.x), float(p.y), float(p.z)] for p in points])
    obj["af_fiber_points_mode"] = "BAKE" if bake else "INTERACTIVE"
    obj["af_fiber_points_signature"] = signature


def clear_curve_points(obj):
    telemetry_count("fiber_writes")
    curve = obj.data
    _clear_splines(curve)
    _clear_fiber_points_cache(obj)
    obj["af_fiber_points_world"] = "[]"
    obj["af_fiber_points_mode"] = "INTERACTIVE"
    obj["af_fiber_points_signature"] = ""
    obj["af_fiber_output_state"] = "INVALID"


def get_scp_proxy(scene, root_name, scp_id):
    return find_geometry_scp_obj(scene, root_name, scp_id)


def _depsgraph_for_obj(obj):
    return depsgraph_for_scene(scene_for_id(obj))


def _open_eval_mesh(obj):
    depsgraph = _depsgraph_for_obj(obj)
    obj_eval = None if depsgraph is None else obj.evaluated_get(depsgraph)
    mesh_eval = None if obj_eval is None else obj_eval.to_mesh()
    if mesh_eval is None or len(mesh_eval.vertices) == 0:
        None if obj_eval is None else obj_eval.to_mesh_clear()
        return None, None
    return obj_eval, mesh_eval


def _is_mesh_obj(obj):
    return obj is not None and obj.type == "MESH" and obj.data is not None


def _shape_index(mesh, payload):
    try:
        param = max(0.0, min(1.0, float(payload)))
    except Exception:
        param = 0.0
    if len(mesh.vertices) <= 1:
        return 0
    return max(0, min(len(mesh.vertices) - 1, int(round(param * float(len(mesh.vertices) - 1)))))


def _mesh_local_point_from_shape_param(parent_obj, payload):
    if not _is_mesh_obj(parent_obj):
        return None
    obj_eval, mesh_eval = _open_eval_mesh(parent_obj)
    if mesh_eval is None:
        return None
    try:
        return mesh_eval.vertices[_shape_index(mesh_eval, payload)].co.copy()
    finally:
        obj_eval.to_mesh_clear()


def _vertex_signature_ok(mesh_eval, raw):
    wanted = fiber_attach_signature(raw)
    return wanted == "" or wanted == mesh_topology_signature(mesh_eval)


def _mesh_local_point_from_vertex_index(parent_obj, payload, raw):
    obj_eval, mesh_eval = _open_eval_mesh(parent_obj)
    if mesh_eval is None:
        return None
    try:
        if not _vertex_signature_ok(mesh_eval, raw):
            return None
        index = max(0, min(len(mesh_eval.vertices) - 1, int(payload)))
        return mesh_eval.vertices[index].co.copy()
    finally:
        obj_eval.to_mesh_clear()


def _mesh_world_normal_from_vertex_index(parent_obj, payload, raw):
    obj_eval, mesh_eval = _open_eval_mesh(parent_obj)
    if mesh_eval is None:
        return None
    try:
        if not _vertex_signature_ok(mesh_eval, raw):
            return None
        index = max(0, min(len(mesh_eval.vertices) - 1, int(payload)))
        return _world_normal(parent_obj, mesh_eval.vertices[index].normal.copy())
    finally:
        obj_eval.to_mesh_clear()


def _local_from_attach(proxy, mode, payload, raw):
    if mode == "mesh_anchor":
        return payload
    if mode == "shape_param_v1":
        return _mesh_local_point_from_shape_param(proxy, payload)
    if mode == "mesh_vertex_v1":
        return _mesh_local_point_from_vertex_index(proxy, payload, raw)
    return None


def _world_normal(parent_obj, normal):
    if Vector(normal).length <= 1.0e-8:
        return None
    matrix = parent_obj.matrix_world.to_3x3().inverted().transposed()
    return (matrix @ Vector(normal)).normalized()


def attach_world_normal(root, scene, runtime_registry, parent_id, attach_param_raw):
    return resolve_attachment_normal(root, scene, parent_id, attach_param_raw, runtime_registry)


def endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw):
    return resolve_attachment_world(root, scene, parent_id, attach_param_raw, runtime_registry)


def touch_world(root, scene, runtime_registry, touch):
    world = endpoint_world(root, scene, runtime_registry, touch.parent_id, touch.attach_param)
    offset = float(getattr(touch, "normal_offset", 0.0))
    if world is None or abs(offset) <= 1.0e-9:
        return world
    normal = attach_world_normal(root, scene, runtime_registry, touch.parent_id, touch.attach_param)
    return world if normal is None else world + normal * offset


def _nearest_eval_vertex(parent_proxy, moved_world):
    obj_eval, mesh_eval = _open_eval_mesh(parent_proxy)
    if mesh_eval is None:
        return None, 0, 0, ""
    try:
        best = min(mesh_eval.vertices, key=lambda v: ((parent_proxy.matrix_world @ v.co) - moved_world).length_squared)
        return best.co.copy(), best.index, len(mesh_eval.vertices), mesh_topology_signature(mesh_eval)
    finally:
        obj_eval.to_mesh_clear()


def nearest_param(parent_scp, parent_proxy, moved_world):
    _ = parent_scp
    if not _is_mesh_obj(parent_proxy):
        return 0.0
    _local, index, count, _signature = _nearest_eval_vertex(parent_proxy, moved_world)
    if count == 0:
        return 0.0
    if count <= 1:
        return 0.0
    return float(index) / float(count - 1)


def _first_window_manager():
    managers = tuple(getattr(bpy.data, "window_managers", ()) or ())
    return managers[0] if managers else None


def _iter_view3d_areas(window_manager):
    for win in getattr(window_manager, "windows", ()):
        for area in getattr(getattr(win, "screen", None), "areas", ()):
            if area.type == "VIEW_3D":
                yield area


def _view3d_region(area):
    return next((r for r in area.regions if r.type == "WINDOW"), None)


def _view3d_space(area):
    return next((sp.region_3d for sp in area.spaces if sp.type == "VIEW_3D"), None)


def get_active_view3d_region(window_manager=None):
    wm = window_manager or _first_window_manager()
    if wm is None:
        return None, None
    for area in _iter_view3d_areas(wm):
        region = _view3d_region(area)
        rv3d = _view3d_space(area)
        if region is not None and rv3d is not None:
            return region, rv3d
    return None, None


def world_units_per_pixel(world_loc, window_manager=None):
    region, rv3d = get_active_view3d_region(window_manager)
    if region is None or rv3d is None:
        return None
    p2d = view3d_utils.location_3d_to_region_2d(region, rv3d, world_loc)
    if p2d is None:
        return None
    p2d_2 = Vector((p2d.x + 1.0, p2d.y))
    w2 = view3d_utils.region_2d_to_location_3d(region, rv3d, p2d_2, world_loc)
    return (w2 - world_loc).length
