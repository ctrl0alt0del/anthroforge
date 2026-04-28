import bpy


def get_collection(scene, name):
    return scene.collection.children.get(name)


def scp_prop_map(root):
    return {s.id: s for s in root.af_scp_system.scps}


def fiber_prop_map(root):
    return {f.id: f for f in root.af_vcp_system.fibers}


def find_scp_proxy_obj(scp_col, root_name, scp_id):
    if scp_col is None:
        return None
    for obj in scp_col.objects:
        if (
            obj.get("af_proxy")
            and not obj.get("af_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_scp_id") == scp_id
        ):
            return obj
    return None


def find_source_fiber_obj(vcp_col, root_name, fiber_id):
    if vcp_col is None:
        return None
    for obj in vcp_col.objects:
        if (
            obj.get("af_fiber_proxy")
            and not obj.get("af_fiber_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_fiber_id") == fiber_id
        ):
            return obj
    return None


def find_source_muscle_obj(vcp_col, root_name, muscle_id, surface):
    if vcp_col is None:
        return None
    for obj in vcp_col.objects:
        if (
            obj.get("af_muscle_proxy")
            and not obj.get("af_muscle_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_muscle_id") == muscle_id
            and obj.get("af_muscle_surface") == surface
        ):
            return obj
    return None


def find_mirror_scp_obj(scp_col, root_name, scp_id):
    if scp_col is None:
        return None
    for obj in scp_col.objects:
        if (
            obj.get("af_proxy")
            and obj.get("af_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_source_scp_id") == scp_id
        ):
            return obj
    return None


def find_mirror_fiber_obj(vcp_col, root_name, source_fiber_id):
    if vcp_col is None:
        return None
    for obj in vcp_col.objects:
        if (
            obj.get("af_fiber_proxy")
            and obj.get("af_fiber_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_source_fiber_id") == source_fiber_id
        ):
            return obj
    return None


def find_mirror_muscle_obj(vcp_col, root_name, source_muscle_id, surface):
    if vcp_col is None:
        return None
    for obj in vcp_col.objects:
        if (
            obj.get("af_muscle_proxy")
            and obj.get("af_muscle_mirror_proxy")
            and obj.get("af_root_name") == root_name
            and obj.get("af_source_muscle_id") == source_muscle_id
            and obj.get("af_muscle_surface") == surface
        ):
            return obj
    return None


def remove_obj(obj):
    if obj is None:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)


def ensure_obj_type(obj, src_obj):
    if obj is None:
        return None
    if src_obj.type == "MESH" and obj.type != "MESH":
        return None
    if src_obj.type == "CURVE" and obj.type != "CURVE":
        return None
    return obj


def create_mirror_from_source(collection, src_obj, name):
    if src_obj.type == "MESH":
        data = bpy.data.meshes.new(f"{name}_mesh")
    elif src_obj.type == "CURVE":
        data = bpy.data.curves.new(f"{name}_curve", type="CURVE")
    else:
        return None
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    return obj


def copy_mesh_data(src_obj, dst_obj):
    src = src_obj.data
    verts = [v.co.copy() for v in src.vertices]
    faces = [tuple(p.vertices) for p in src.polygons]
    dst = dst_obj.data
    dst.clear_geometry()
    dst.from_pydata(verts, [], faces)
    dst.update()


def copy_curve_data(src_obj, dst_obj):
    src = src_obj.data
    dst = dst_obj.data

    dst.dimensions = src.dimensions
    dst.fill_mode = src.fill_mode
    dst.bevel_depth = src.bevel_depth
    dst.bevel_resolution = src.bevel_resolution
    dst.resolution_u = src.resolution_u

    while dst.splines:
        dst.splines.remove(dst.splines[0])

    for s in src.splines:
        ns = dst.splines.new(type=s.type)
        _copy_spline_points(s, ns)
        ns.use_cyclic_u = s.use_cyclic_u


def _copy_spline_points(src_spline, dst_spline):
    if src_spline.type == "BEZIER":
        _copy_bezier_points(src_spline, dst_spline)
        return
    _copy_poly_points(src_spline, dst_spline)


def _copy_bezier_points(src_spline, dst_spline):
    dst_spline.bezier_points.add(len(src_spline.bezier_points) - 1)
    for i, bp in enumerate(src_spline.bezier_points):
        nbp = dst_spline.bezier_points[i]
        nbp.co = bp.co.copy()
        nbp.handle_left = bp.handle_left.copy()
        nbp.handle_right = bp.handle_right.copy()
        nbp.handle_left_type = bp.handle_left_type
        nbp.handle_right_type = bp.handle_right_type
        nbp.radius = bp.radius
        nbp.tilt = bp.tilt


def _copy_poly_points(src_spline, dst_spline):
    dst_spline.points.add(len(src_spline.points) - 1)
    for i, p in enumerate(src_spline.points):
        dst_spline.points[i].co = p.co[:]
        dst_spline.points[i].radius = p.radius
        dst_spline.points[i].tilt = p.tilt


def copy_data(src_obj, dst_obj):
    if src_obj.type == "MESH":
        copy_mesh_data(src_obj, dst_obj)
    elif src_obj.type == "CURVE":
        copy_curve_data(src_obj, dst_obj)


def ensure_mirror_material(obj, alpha_mult=0.35):
    if obj is None or obj.data is None or not hasattr(obj.data, "materials"):
        return
    src_mat = obj.data.materials[0] if obj.data.materials else None
    base_name = src_mat.name if src_mat else f"AF_MIRROR_{obj.name}"
    mir_name = f"{base_name}_MIR"

    mat = bpy.data.materials.get(mir_name)
    if mat is None:
        mat = bpy.data.materials.new(mir_name)
        mat.use_nodes = False

    if src_mat is not None:
        r, g, b, a = src_mat.diffuse_color
    else:
        r, g, b, a = (0.8, 0.8, 0.8, 1.0)

    mat.diffuse_color = (r, g, b, max(0.05, min(1.0, a * alpha_mult)))

    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "show_transparent_back"):
        mat.show_transparent_back = True

    obj.data.materials.clear()
    obj.data.materials.append(mat)
