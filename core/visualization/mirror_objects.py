import bpy
import json


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


def clone_native_object(collection, src_obj, name):
    obj = src_obj.copy()
    obj.name = name
    obj.data = None if getattr(src_obj, "data", None) is None else src_obj.data.copy()
    obj.parent = None
    collection.objects.link(obj)
    return obj


def remap_object_cluster_refs(obj_map):
    for obj in obj_map.values():
        _remap_owner_refs(obj, obj_map, {"parent"})
        _remap_owner_refs(getattr(obj, "data", None), obj_map)
        _remap_iter_refs(getattr(obj, "modifiers", ()), obj_map)
        _remap_iter_refs(getattr(obj, "constraints", ()), obj_map)


def _remap_iter_refs(items, obj_map):
    for item in items or ():
        _remap_owner_refs(item, obj_map)


def _remap_owner_refs(owner, obj_map, skip=()):
    if owner is None or not hasattr(owner, "bl_rna"):
        return
    for prop in owner.bl_rna.properties:
        _remap_pointer_prop(owner, prop, obj_map, set(skip or ()))


def _remap_pointer_prop(owner, prop, obj_map, skip):
    key = prop.identifier
    if key == "rna_type" or key in skip or prop.is_readonly or prop.type != "POINTER":
        return
    value = getattr(owner, key, None)
    if value in obj_map:
        setattr(owner, key, obj_map[value])


def remap_object_cluster_parents(obj_map):
    for src_obj, clone in obj_map.items():
        _remap_parent(src_obj, clone, obj_map)


def _remap_parent(src_obj, clone, obj_map):
    parent = obj_map.get(getattr(src_obj, "parent", None))
    if parent is None:
        return
    world = clone.matrix_world.copy()
    clone.parent = parent
    clone.matrix_world = world


def copy_mesh_data(src_obj, dst_obj):
    src = src_obj.data
    verts = [v.co.copy() for v in src.vertices]
    faces = [tuple(p.vertices) for p in src.polygons]
    dst = dst_obj.data
    dst.clear_geometry()
    dst.from_pydata(verts, [], faces)
    dst.update()


def copy_curve_data(src_obj, dst_obj):
    src, dst = src_obj.data, dst_obj.data
    _copy_curve_shape_settings(src, dst)
    _clear_splines(dst)
    _copy_splines(src, dst)


def _copy_curve_shape_settings(src, dst):
    dst.dimensions = src.dimensions
    dst.fill_mode = src.fill_mode
    dst.bevel_depth = src.bevel_depth
    dst.bevel_resolution = src.bevel_resolution
    dst.resolution_u = src.resolution_u


def _clear_splines(curve):
    while curve.splines:
        curve.splines.remove(curve.splines[0])


def _copy_splines(src, dst):
    for spline in src.splines:
        new_spline = dst.splines.new(type=spline.type)
        _copy_spline_points(spline, new_spline)
        new_spline.use_cyclic_u = spline.use_cyclic_u


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
    ensure_private_data(dst_obj)
    if src_obj.type == "MESH":
        copy_mesh_data(src_obj, dst_obj)
    elif src_obj.type == "CURVE":
        copy_curve_data(src_obj, dst_obj)


def share_source_data(src_obj, dst_obj):
    source, previous = getattr(src_obj, "data", None), getattr(dst_obj, "data", None)
    if source is None: return False
    if previous is not source:
        _remember_curve_snapshot(source, dst_obj)
        dst_obj.data = source; _remove_orphan_data(previous)
    dst_obj["af_mirror_shared_data"] = True
    dst_obj["af_mirror_data_source"] = str(src_obj.name)
    return True


def ensure_private_data(obj):
    if obj is None or not bool(obj.get("af_mirror_shared_data")): return
    if getattr(obj, "data", None) is not None: obj.data = obj.data.copy()
    for key in ("af_mirror_shared_data", "af_mirror_data_source"):
        if key in obj: del obj[key]


def detach_shared_mirrors(source):
    data = None if source is None else getattr(source, "data", None)
    if data is None or data.users <= 1: return
    for obj in tuple(bpy.data.objects):
        if obj is not source and getattr(obj, "data", None) is data and _shares_from(obj, source):
            ensure_private_data(obj)


def _shares_from(obj, source):
    return bool(obj.get("af_mirror_shared_data") and
                obj.get("af_mirror_data_source") == str(source.name))


def restore_curve_snapshot(obj):
    raw = "" if obj is None else str(obj.get("af_mirror_curve_snapshot", "") or "")
    if not raw or getattr(obj, "type", "") != "CURVE": return False
    try: rows = json.loads(raw)
    except Exception: return False
    ensure_private_data(obj); _clear_splines(obj.data)
    for row in rows: _restore_poly_spline(obj.data, row)
    return True


def _remember_curve_snapshot(data, obj):
    if not isinstance(data, bpy.types.Curve): return
    rows = tuple(_poly_snapshot(row) for row in data.splines)
    if all(row is not None for row in rows): obj["af_mirror_curve_snapshot"] = json.dumps(rows)


def _poly_snapshot(spline):
    if str(spline.type) != "POLY": return None
    points = tuple(tuple(float(value) for value in point.co) for point in spline.points)
    return {"points": points, "cyclic": bool(spline.use_cyclic_u)}


def _restore_poly_spline(curve, row):
    points = tuple(row.get("points", ())); spline = curve.splines.new(type="POLY")
    spline.points.add(max(0, len(points) - 1))
    if points: spline.points.foreach_set("co", tuple(value for point in points for value in point))
    spline.use_cyclic_u = bool(row.get("cyclic", False))


def _remove_orphan_data(data):
    if data is None or data.users: return
    if isinstance(data, bpy.types.Mesh): bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Curve): bpy.data.curves.remove(data)


def ensure_mirror_material(obj, alpha_mult=0.35):
    if obj is None or obj.data is None or not hasattr(obj.data, "materials"):
        return
    ensure_private_data(obj)
    src_mat = obj.data.materials[0] if obj.data.materials else None
    mat = _ensure_material(_mirror_material_name(obj, src_mat))
    mat.diffuse_color = _mirror_color(src_mat, alpha_mult)
    _configure_material(mat)
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def _mirror_material_name(obj, src_mat):
    base_name = src_mat.name if src_mat else f"AF_MIRROR_{obj.name}"
    return f"{base_name}_MIR"


def _ensure_material(name):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = False
    return mat


def _mirror_color(src_mat, alpha_mult):
    color = src_mat.diffuse_color if src_mat is not None else (0.8, 0.8, 0.8, 1.0)
    r, g, b, a = color
    return (r, g, b, max(0.05, min(1.0, a * alpha_mult)))


def _configure_material(mat):
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"
    if hasattr(mat, "show_transparent_back"):
        mat.show_transparent_back = True
