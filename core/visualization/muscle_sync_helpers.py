import bpy
import hashlib

from ..deps.control_lifecycle import mark_dynamic_control_object
from ..perf_trace import perf_count, perf_time, perf_timer
from ..scp_runtime.object_colors import apply_object_color
from ..scp_runtime.surface import surface_bvh_local
from ..utils import scene_for_id


def get_vis_collection(scene, collection_name):
    col = scene.collection.children.get(collection_name)
    if col is None:
        col = bpy.data.collections.new(collection_name)
        scene.collection.children.link(col)
    return col


def _indexed(index, bucket, key):
    return None if index is None else dict(index.get(bucket, {})).get(key)


def find_muscle_proxy(vis_col, root_name, muscle_id, surface_type="BASE", index=None):
    indexed = _indexed(index, "muscle", (str(muscle_id or ""), str(surface_type or "")))
    if indexed is not None:
        return indexed
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


def resolve_muscle_surface(root, muscle_id, surface_role, scene=None):
    scene = scene or scene_for_id(root)
    collection = None if scene is None else get_vis_collection(scene, "AF_VCP_VIS")
    return None if collection is None else find_muscle_proxy(collection, root.name, muscle_id, surface_role)


def find_inflation_ctrl(vis_col, root_name, muscle_id, index=None):
    indexed = _indexed(index, "inflation", str(muscle_id or ""))
    if _live_object(indexed):
        return indexed
    return _find_inflation_ctrl_in_collection(vis_col, root_name, muscle_id) or _find_inflation_ctrl_global(root_name, muscle_id)


def _live_object(obj):
    if obj is None:
        return False
    try:
        return bpy.data.objects.get(obj.name) == obj
    except ReferenceError:
        return False


def _find_inflation_ctrl_in_collection(vis_col, root_name, muscle_id):
    for obj in vis_col.objects:
        if (
            obj.get("af_muscle_inflation_ctrl")
            and obj.get("af_root_name") == root_name
            and obj.get("af_muscle_id") == muscle_id
        ):
            return obj
    return None


def _find_inflation_ctrl_global(root_name, muscle_id):
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
    mark_dynamic_control_object(obj)
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


def mark_inflation_ctrl_location(obj):
    if obj is not None:
        obj["af_muscle_ctrl_sync_location"] = [float(value) for value in obj.location]


def inflation_ctrl_location_changed(obj, epsilon=1.0e-7):
    stored = None if obj is None else obj.get("af_muscle_ctrl_sync_location")
    if stored is None or len(stored) != 3:
        return True
    return any(abs(float(obj.location[i]) - float(stored[i])) > epsilon for i in range(3))


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

    apply_object_color(obj, mat.diffuse_color)
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def update_mesh(obj, verts, faces):
    scene, start = scene_for_id(obj), perf_timer()
    try:
        _update_mesh_payload(obj, verts, faces)
    finally:
        perf_time(scene, "muscle_mesh_update", start)


def _update_mesh_payload(obj, verts, faces):
    mesh = obj.data
    sig, topo = _mesh_signature(verts, faces), _topology_signature(faces)
    if obj.get("af_mesh_signature") == sig:
        perf_count(scene_for_id(obj), "mesh_rewrite_skipped")
        return
    if _same_topology(obj, mesh, verts, topo):
        _update_mesh_vertices(obj, mesh, verts, sig)
        return
    _rebuild_mesh(obj, mesh, verts, faces, sig, topo)


def _same_topology(obj, mesh, verts, topo):
    return obj.get("af_mesh_topology_signature") == topo and len(mesh.vertices) == len(verts)


def _update_mesh_vertices(obj, mesh, verts, sig):
    mesh.vertices.foreach_set("co", _flat_verts(verts))
    mesh.update()
    obj["af_mesh_signature"] = sig


def _rebuild_mesh(obj, mesh, verts, faces, sig, topo):
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj["af_mesh_signature"] = sig
    obj["af_mesh_topology_signature"] = topo


def _flat_verts(verts):
    return [float(value) for co in verts for value in _co3(co)]


def _co3(co):
    return (float(co.x), float(co.y), float(co.z)) if hasattr(co, "x") else (float(co[0]), float(co[1]), float(co[2]))


def _topology_signature(faces):
    h = hashlib.sha1()
    for face in tuple(faces or ()):
        h.update((",".join(str(int(v)) for v in face) + ";").encode())
    return h.hexdigest()


def _mesh_signature(verts, faces):
    h = hashlib.sha1(_topology_signature(faces).encode())
    for co in tuple(verts or ()):
        h.update("|{:.6f},{:.6f},{:.6f}".format(*_co3(co)).encode())
    return h.hexdigest()


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


def _surface_bvh(mesh_obj):
    return surface_bvh_local(mesh_obj)


def nearest_on_mesh_surface(mesh_obj, world_point):
    if mesh_obj is None or mesh_obj.type != "MESH":
        return None
    try:
        bvh = _surface_bvh(mesh_obj)
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
