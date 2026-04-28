import bpy
import bmesh
from mathutils import Vector

from ..vcp.blob import BlobVCPRuntime
from ..scp_runtime.common import find_geometry_scp_obj


def get_vis_collection(scene, collection_name):
    col = scene.collection.children.get(collection_name)
    if col is None:
        col = bpy.data.collections.new(collection_name)
        scene.collection.children.link(col)
    return col


def find_blob_proxy(vis_col, root_name, blob_id):
    for obj in vis_col.objects:
        if (
            obj.get("af_blob_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_blob_id") == blob_id
            and not obj.get("af_blob_mirror_proxy")
        ):
            return obj
    return None


def find_blob_control(vis_col, root_name, blob_id):
    for obj in vis_col.objects:
        if (
            obj.get("af_blob_control_gizmo")
            and obj.get("af_root_name") == root_name
            and obj.get("af_blob_id") == blob_id
        ):
            return obj
    return None


def create_blob_proxy(vis_col, root, blob_id):
    mesh = bpy.data.meshes.new(f"AF_{blob_id}_mesh")
    obj = bpy.data.objects.new(f"AF_{blob_id}", mesh)
    obj["af_blob_proxy"] = True
    obj["af_root_name"] = root.name
    obj["af_blob_id"] = blob_id
    vis_col.objects.link(obj)
    return obj


def create_blob_control(vis_col, root, blob_id):
    ctrl = bpy.data.objects.new(f"AF_{blob_id}_CTRL", None)
    ctrl.empty_display_type = "SPHERE"
    ctrl.empty_display_size = 0.04
    ctrl.show_in_front = True
    ctrl.hide_render = True
    ctrl["af_blob_control_gizmo"] = True
    ctrl["af_root_name"] = root.name
    ctrl["af_blob_id"] = blob_id
    vis_col.objects.link(ctrl)
    return ctrl


def ensure_blob_material(obj, active=False, default_blob_color=(0.72, 0.52, 0.40, 0.55), selected_blob_color=(1.0, 0.25, 0.25, 0.80)):
    if obj.data is None or not hasattr(obj.data, "materials"):
        return
    name = f"AF_BLOB_MAT_{obj.get('af_blob_id', obj.name)}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = False
    mat.diffuse_color = selected_blob_color if active else default_blob_color
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def remove_proxy(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def remove_ctrl(obj):
    bpy.data.objects.remove(obj, do_unlink=True)


def _find_muscle_surface(scene, root_name, muscle_id, surface):
    for o in scene.objects:
        if (
            o.get("af_muscle_proxy")
            and not o.get("af_muscle_mirror_proxy")
            and o.get("af_root_name") == root_name
            and o.get("af_muscle_id") == muscle_id
        ):
            if o.get("af_muscle_surface") == surface:
                return o
    return None


def _find_scp_target(scene, root_name, scp_id):
    return find_geometry_scp_obj(scene, root_name, scp_id)


def target_object_for_blob(scene, root, blob_prop):
    t = blob_prop.attach_target_type
    if t == "MUSCLE" and blob_prop.attach_target_id:
        infl = _find_muscle_surface(scene, root.name, blob_prop.attach_target_id, "INFL")
        if infl is not None:
            return infl
        return _find_muscle_surface(scene, root.name, blob_prop.attach_target_id, "BASE")
    if t == "SCP" and blob_prop.attach_target_id:
        return _find_scp_target(scene, root.name, blob_prop.attach_target_id)
    if t == "OBJECT" and blob_prop.attach_target_object_name:
        return scene.objects.get(blob_prop.attach_target_object_name)
    return None


def unit_local_mesh(blob):
    subd = 1
    if blob.resolution >= 24:
        subd = 2
    if blob.resolution >= 64:
        subd = 3
    if blob.resolution >= 128:
        subd = 4

    bm = bmesh.new()
    try:
        bmesh.ops.create_icosphere(bm, subdivisions=subd, radius=1.0)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        verts_local = [v.co.copy() for v in bm.verts]
        faces = [tuple(v.index for v in f.verts) for f in bm.faces]
        return verts_local, faces
    finally:
        bm.free()


def apply_initial_transform_from_prop(obj, bp):
    obj.location = Vector(bp.center_world)
    if bp.shape == "ELLIPSOID":
        obj.scale = Vector(
            (
                max(1e-6, bp.radius * bp.axis_scale[0]),
                max(1e-6, bp.radius * bp.axis_scale[1]),
                max(1e-6, bp.radius * bp.axis_scale[2]),
            )
        )
    else:
        r = max(1e-6, bp.radius)
        obj.scale = Vector((r, r, r))


def runtime_from_proxy_transform(bp, obj):
    runtime = BlobVCPRuntime.from_prop(bp)
    runtime.center_world = obj.matrix_world.to_translation().copy()
    return runtime


def update_mesh_from_world(obj, world_verts, faces):
    mesh = obj.data
    mesh.clear_geometry()
    m_inv = obj.matrix_world.inverted()
    local_verts = [m_inv @ v for v in world_verts]
    verts = [(v.x, v.y, v.z) for v in local_verts]
    mesh.from_pydata(verts, [], faces)
    mesh.update()


def vec_changed(a, b, eps=1e-8):
    return (Vector(a) - Vector(b)).length > eps
