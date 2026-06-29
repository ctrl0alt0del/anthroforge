import bpy
import json
from mathutils import Vector
from bpy_extras import view3d_utils

from ..deps.control_lifecycle import mark_dynamic_control_object
from ..scp_runtime.object_colors import apply_object_color
from ..attachment_codec import fiber_attach_signature, parse_fiber_attach_param
from ..scp_proxy.signature import mesh_topology_signature
from ..utils import depsgraph_for_scene, scene_for_id
from ..scp_runtime.common import find_geometry_scp_obj


def get_vis_collection(scene, collection_name):
    col = scene.collection.children.get(collection_name)
    if col is None:
        col = bpy.data.collections.new(collection_name)
        scene.collection.children.link(col)
    return col


def find_fiber_proxy(vis_col, root_name, fiber_id):
    for obj in vis_col.objects:
        if (
            obj.get("af_fiber_proxy")
            and not obj.get("af_fiber_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_fiber_id") == fiber_id
        ):
            return obj
    return None


def _find_with(objects, predicate):
    return next((obj for obj in objects if predicate(obj)), None)


def _endpoint_match(obj, root_name, fiber_id, endpoint):
    return (
        obj.get("af_fiber_endpoint_handle")
        and obj.get("af_root_name") == root_name
        and obj.get("af_fiber_id") == fiber_id
        and obj.get("af_fiber_endpoint") == endpoint
    )


def find_endpoint_handle(vis_col, root_name, fiber_id, endpoint):
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


def find_touch_handle(vis_col, root_name, fiber_id, touch_index):
    return _find_with(
        vis_col.objects,
        lambda obj: _touch_match(obj, root_name, fiber_id, touch_index),
    ) or _find_with(
        bpy.data.objects,
        lambda obj: _touch_match(obj, root_name, fiber_id, touch_index),
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


def update_curve_points(obj, points, thickness, bake=False, cyclic=False):
    curve = obj.data
    while curve.splines:
        curve.splines.remove(curve.splines[0])

    spline = curve.splines.new(type="POLY")
    spline.points.add(len(points) - 1)
    for i, p in enumerate(points):
        spline.points[i].co = (p.x, p.y, p.z, 1.0)
    spline.use_cyclic_u = bool(cyclic and len(points) > 2)

    curve.bevel_depth = max(0.0, float(thickness))
    curve.fill_mode = "FULL"
    obj["af_fiber_points_world"] = json.dumps([[float(p.x), float(p.y), float(p.z)] for p in points])
    obj["af_fiber_points_mode"] = "BAKE" if bake else "INTERACTIVE"


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


def _local_from_attach(proxy, mode, payload, raw):
    if mode == "mesh_anchor":
        return payload
    if mode == "shape_param_v1":
        return _mesh_local_point_from_shape_param(proxy, payload)
    if mode == "mesh_vertex_v1":
        return _mesh_local_point_from_vertex_index(proxy, payload, raw)
    return None


def endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw):
    _ = runtime_registry
    if not parent_id:
        return None
    proxy = get_scp_proxy(scene, root.name, parent_id)
    if proxy is None:
        return None
    mode, payload = parse_fiber_attach_param(attach_param_raw)
    local = _local_from_attach(proxy, mode, payload, attach_param_raw)
    if local is None:
        return None
    return proxy.matrix_world @ local


def _nearest_eval_vertex(parent_proxy, moved_world):
    obj_eval, mesh_eval = _open_eval_mesh(parent_proxy)
    if mesh_eval is None:
        return None, 0, 0
    try:
        best = min(mesh_eval.vertices, key=lambda v: ((parent_proxy.matrix_world @ v.co) - moved_world).length_squared)
        return best.co.copy(), best.index, len(mesh_eval.vertices)
    finally:
        obj_eval.to_mesh_clear()


def nearest_param(parent_scp, parent_proxy, moved_world):
    _ = parent_scp
    if not _is_mesh_obj(parent_proxy):
        return 0.0
    _local, index, count = _nearest_eval_vertex(parent_proxy, moved_world)
    if count == 0:
        return 0.0
    if count <= 1:
        return 0.0
    return float(index) / float(count - 1)


def nearest_parent_mesh_vertex_local_point(parent_proxy, moved_world):
    if not _is_mesh_obj(parent_proxy):
        return None
    local, _index, _count = _nearest_eval_vertex(parent_proxy, moved_world)
    return local


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
