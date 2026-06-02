import bpy
from mathutils.bvhtree import BVHTree


def get_vis_collection(scene, collection_name):
    col = scene.collection.children.get(collection_name)
    if col is None:
        col = bpy.data.collections.new(collection_name)
        scene.collection.children.link(col)
    return col


def find_muscle_proxy(vis_col, root_name, muscle_id, surface_type="BASE"):
    for obj in vis_col.objects:
        if (
            obj.get("af_muscle_proxy")
            and not obj.get("af_muscle_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_muscle_id") == muscle_id
            and obj.get("af_muscle_surface") == surface_type
        ):
            return obj
    return None


def find_inflation_ctrl(vis_col, root_name, muscle_id):
    for obj in vis_col.objects:
        if (
            obj.get("af_muscle_inflation_ctrl")
            and obj.get("af_root_name") == root_name
            and obj.get("af_muscle_id") == muscle_id
        ):
            return obj
    for obj in bpy.data.objects:
        if (
            obj.get("af_muscle_inflation_ctrl")
            and obj.get("af_root_name") == root_name
            and obj.get("af_muscle_id") == muscle_id
        ):
            return obj
    return None


def create_muscle_proxy(vis_col, root, muscle_id, surface_type):
    suffix = "" if surface_type == "BASE" else "_INFL"
    mesh = bpy.data.meshes.new(f"AF_{muscle_id}{suffix}_mesh")
    obj = bpy.data.objects.new(f"AF_{muscle_id}{suffix}", mesh)
    obj["af_muscle_proxy"] = True
    obj["af_root_name"] = root.name
    obj["af_muscle_id"] = muscle_id
    obj["af_muscle_surface"] = surface_type
    vis_col.objects.link(obj)
    return obj


def create_inflation_ctrl(vis_col, root, muscle_id):
    obj = bpy.data.objects.new(f"AF_{muscle_id}_INFL_MAX", None)
    mark_inflation_ctrl(obj, root, muscle_id, apply_visual_defaults=True)
    vis_col.objects.link(obj)
    return obj


def mark_inflation_ctrl(obj, root, muscle_id, apply_visual_defaults=False):
    if obj is None:
        return None
    if bool(apply_visual_defaults):
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.04
        obj.show_in_front = True
        obj.hide_render = True
    obj["af_muscle_inflation_ctrl"] = True
    obj["af_root_name"] = root.name
    obj["af_muscle_id"] = muscle_id
    return obj


def ensure_material(obj, active=False):
    if obj.data is None or not hasattr(obj.data, "materials"):
        return

    surf = obj.get("af_muscle_surface", "BASE")
    mat_name = f"AF_MUSCLE_MAT_{obj.get('af_muscle_id', obj.name)}_{surf}"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = False

    if surf == "BASE":
        mat.diffuse_color = (0.35, 0.20, 0.18, 0.35) if not active else (0.45, 0.25, 0.22, 0.45)
    else:
        mat.diffuse_color = (0.80, 0.35, 0.30, 0.80) if active else (0.72, 0.42, 0.32, 0.65)

    obj.data.materials.clear()
    obj.data.materials.append(mat)


def update_mesh(obj, verts, faces):
    mesh = obj.data
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()


def remove_proxy_obj(obj):
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        bpy.data.meshes.remove(data)


def remove_ctrl_obj(obj):
    if obj is not None:
        bpy.data.objects.remove(obj, do_unlink=True)


def nearest_on_mesh_surface(mesh_obj, world_point):
    if mesh_obj is None or mesh_obj.type != "MESH":
        return None
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bvh = BVHTree.FromObject(mesh_obj, depsgraph)
    except Exception:
        bvh = None
    if bvh is None:
        return None

    mwi = mesh_obj.matrix_world.inverted()
    local = mwi @ world_point
    hit = bvh.find_nearest(local)
    if hit is None:
        return None
    co_local = hit[0]
    if co_local is None:
        return None
    return mesh_obj.matrix_world @ co_local


def collect_fiber_props(root, muscle):
    fibers_by_id = {f.id: f for f in root.af_vcp_system.fibers}
    ordered = []
    missing = []
    for ref in muscle.fiber_refs:
        f = fibers_by_id.get(ref.fiber_id)
        if f is None:
            missing.append(ref.fiber_id)
        else:
            ordered.append(f)
    return ordered, missing
