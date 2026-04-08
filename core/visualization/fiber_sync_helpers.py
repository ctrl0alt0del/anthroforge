import bpy
import json
from mathutils import Vector
from bpy_extras import view3d_utils

from ..attachment_codec import parse_fiber_attach_param


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


def find_endpoint_handle(vis_col, root_name, fiber_id, endpoint):
    for obj in vis_col.objects:
        if (
            obj.get("af_fiber_endpoint_handle")
            and obj.get("af_root_name") == root_name
            and obj.get("af_fiber_id") == fiber_id
            and obj.get("af_fiber_endpoint") == endpoint
        ):
            return obj
    return None


def find_touch_handle(vis_col, root_name, fiber_id, touch_index):
    for obj in vis_col.objects:
        if (
            obj.get("af_fiber_touch_handle")
            and obj.get("af_root_name") == root_name
            and obj.get("af_fiber_id") == fiber_id
            and int(obj.get("af_fiber_touch_index", -1)) == int(touch_index)
        ):
            return obj
    return None


def create_endpoint_handle(vis_col, root, fiber_id, endpoint):
    obj = bpy.data.objects.new(f"AF_{fiber_id}_{endpoint}", None)
    obj.empty_display_type = "SPHERE"
    obj.empty_display_size = 0.035
    obj.show_in_front = True
    obj.hide_render = True
    obj["af_fiber_endpoint_handle"] = True
    obj["af_root_name"] = root.name
    obj["af_fiber_id"] = fiber_id
    obj["af_fiber_endpoint"] = endpoint
    vis_col.objects.link(obj)
    return obj


def create_touch_handle(vis_col, root, fiber_id, touch_index):
    obj = bpy.data.objects.new(f"AF_{fiber_id}_T{touch_index}", None)
    obj.empty_display_type = "CUBE"
    obj.empty_display_size = 0.03
    obj.show_in_front = True
    obj.hide_render = True
    obj["af_fiber_touch_handle"] = True
    obj["af_root_name"] = root.name
    obj["af_fiber_id"] = fiber_id
    obj["af_fiber_touch_index"] = int(touch_index)
    vis_col.objects.link(obj)
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


def update_curve_points(obj, points, thickness, bake=False):
    curve = obj.data
    while curve.splines:
        curve.splines.remove(curve.splines[0])

    spline = curve.splines.new(type="POLY")
    spline.points.add(len(points) - 1)
    for i, p in enumerate(points):
        spline.points[i].co = (p.x, p.y, p.z, 1.0)

    curve.bevel_depth = max(0.0, float(thickness))
    curve.fill_mode = "FULL"
    obj["af_fiber_points_world"] = json.dumps([[float(p.x), float(p.y), float(p.z)] for p in points])
    obj["af_fiber_points_mode"] = "BAKE" if bake else "INTERACTIVE"


def get_scp_proxy(scene, root_name, scp_id):
    for obj in scene.objects:
        if (
            obj.get("af_proxy")
            and not obj.get("af_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_scp_id") == scp_id
        ):
            return obj
    return None


def endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw):
    if not parent_id:
        return None

    scp = runtime_registry.get(parent_id)
    if scp is None:
        return None

    proxy = get_scp_proxy(scene, root.name, parent_id)
    if proxy is None:
        return None

    mode, payload = parse_fiber_attach_param(attach_param_raw)
    if mode == "mesh_anchor":
        local = payload
    elif mode == "shape_param_v1":
        local = scp.shape.compute_local_point(payload)
    else:
        return None

    return proxy.matrix_world @ local


def nearest_param(parent_scp, parent_proxy, moved_world):
    params = parent_scp.shape.get_attach_params()
    if not params:
        return 0.0
    best = params[0]
    best_d2 = None
    for p in params:
        w = parent_proxy.matrix_world @ parent_scp.shape.compute_local_point(p)
        d2 = (w - moved_world).length_squared
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = p
    return best


def nearest_parent_mesh_vertex_local_point(parent_proxy, moved_world):
    if parent_proxy is None or parent_proxy.type != "MESH" or parent_proxy.data is None:
        return None

    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = parent_proxy.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()
    if mesh_eval is None or len(mesh_eval.vertices) == 0:
        if mesh_eval is not None:
            obj_eval.to_mesh_clear()
        return None

    mw = parent_proxy.matrix_world
    best_local = None
    best_d2 = None
    try:
        for v in mesh_eval.vertices:
            w = mw @ v.co
            d2 = (w - moved_world).length_squared
            if best_d2 is None or d2 < best_d2:
                best_d2 = d2
                best_local = v.co.copy()
    finally:
        obj_eval.to_mesh_clear()
    return best_local


def get_active_view3d_region():
    wm = bpy.context.window_manager
    for win in wm.windows:
        screen = win.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            rv3d = None
            for sp in area.spaces:
                if sp.type == "VIEW_3D":
                    rv3d = sp.region_3d
                    break
            if rv3d is None:
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is None:
                continue
            return region, rv3d
    return None, None


def world_units_per_pixel(world_loc):
    region, rv3d = get_active_view3d_region()
    if region is None or rv3d is None:
        return None
    p2d = view3d_utils.location_3d_to_region_2d(region, rv3d, world_loc)
    if p2d is None:
        return None
    p2d_2 = Vector((p2d.x + 1.0, p2d.y))
    w2 = view3d_utils.region_2d_to_location_3d(region, rv3d, p2d_2, world_loc)
    return (w2 - world_loc).length
