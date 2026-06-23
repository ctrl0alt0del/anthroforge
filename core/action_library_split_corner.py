from dataclasses import dataclass, replace

import bpy
from mathutils import Matrix, Vector

from .scp_runtime.bound_objects import clear_scp_tags, find_bound_entry_by_object, iter_bound_objects, set_bound_native_parenting, sync_scp_roles
from .scp_runtime.common import find_scp_by_id, scp_for_object, set_prop_raw
from .scp_runtime.lookup import clear_native_parent_keep_world
from .scp_runtime.object_roles import add_bound_object_to_scp, create_scp, set_scp_geometry_object, set_scp_transform_object
from .scp_runtime.runtime_state import mirror_status, restore_attachment_runtime, snapshot_attachment_runtime
from .utils import get_af_root
from .visualization.mirror_objects import remap_object_cluster_parents, remap_object_cluster_refs
from .visualization.scp_control_helpers import clear_scp_control_marks, mark_scp_control_object

_SCP_SKIP = {"id", "name", "parent_id", "bound_objects", "transform_object_ref", "geometry_object_ref", "color_initialized"}


@dataclass(frozen=True)
class SplitCornerSpec:
    root: object
    scene: object
    source_scp_id: str
    source_name: str
    source_parent_id: str
    source_scalars: tuple
    source_runtime: dict
    bound_items: tuple
    curve_obj: object
    transform_obj: object
    geometry_obj: object
    parent_scp_id: str
    modifier_name: str
    spline_index: int
    split_indices: tuple
    spline_type: str
    point_worlds: tuple


@dataclass(frozen=True)
class BezierPointData:
    co: tuple
    handle_left: tuple
    handle_right: tuple
    handle_left_type: str
    handle_right_type: str
    radius: float
    tilt: float


@dataclass(frozen=True)
class PolyPointData:
    co: tuple
    radius: float
    tilt: float


def split_corner_spec(context):
    scene = None if context is None else getattr(context, "scene", None)
    root = get_af_root(scene)
    error = _context_error(context, root)
    if error:
        return None, error
    return _validated_spec(root, context)


def split_corner(context):
    spec, error = split_corner_spec(context)
    if error:
        return None, error
    bpy.ops.object.mode_set(mode="OBJECT")
    segments = _split_segments(spec)
    clones = _clone_scps(spec, len(segments) - 1)
    curves = _segment_objects(spec.curve_obj, clones)
    geos = _segment_objects(spec.geometry_obj, clones)
    _rewrite_segments(curves, segments)
    _retarget_segments(geos, spec.modifier_name, curves)
    ctrls = _create_controls(spec)
    _bind_segment_hooks(curves, segments, ctrls, spec.spline_type)
    _select_control(context, ctrls[-1])
    return {"clone_scps": tuple(dst for dst, _map in clones), "controls": ctrls}, ""


def _context_error(context, root):
    if context is None or getattr(context, "scene", None) is None:
        return "No active scene."
    if root is None:
        return "AnthroForge root not found in the active scene."
    if str(getattr(context, "mode", "")) != "EDIT_CURVE":
        return "Enter Curve Edit Mode on the SCP curve."
    obj = getattr(context, "active_object", None)
    if obj is None or str(getattr(obj, "type", "")) != "CURVE":
        return "Active object must be the SCP curve object."
    return ""


def _validated_spec(root, context):
    curve_obj = context.active_object
    source_scp = scp_for_object(root, curve_obj)
    error = _source_error(source_scp, curve_obj)
    if error:
        return None, error
    parent_scp = find_scp_by_id(root, getattr(source_scp, "parent_id", ""))
    error = _parent_error(source_scp, parent_scp)
    if error:
        return None, error
    geo, mod, error = _geometry_target(source_scp, curve_obj)
    if error:
        return None, error
    error = _curve_usage_error(curve_obj)
    if error:
        return None, error
    split, error = _selected_split(curve_obj)
    return (None, error) if error else (_build_spec(root, context.scene, source_scp, parent_scp, curve_obj, geo, mod, split), "")


def _source_error(source_scp, curve_obj):
    if source_scp is None:
        return "Active curve is not bound to an SCP."
    if mirror_status(source_scp) != "NONE":
        return "Split by corner is disabled for mirrored SCPs."
    if any(str(getattr(mod, "type", "")) == "HOOK" for mod in curve_obj.modifiers):
        return "Curve already has Hook modifiers."
    return ""


def _parent_error(source_scp, parent_scp):
    if not str(getattr(source_scp, "parent_id", "") or "") or parent_scp is None:
        return "Source SCP must have a parent SCP."
    if getattr(parent_scp, "transform_object_ref", None) is None:
        return "Parent SCP needs a transform object for the shared hook control."
    return ""


def _geometry_target(scp, curve_obj):
    geo = getattr(scp, "geometry_object_ref", None)
    if geo is None:
        return None, None, "Active SCP has no geometry object."
    mods = [mod for mod in geo.modifiers if str(getattr(mod, "type", "")) == "CURVE" and getattr(mod, "object", None) == curve_obj]
    if len(mods) != 1:
        return geo, None, "Geometry object must reference the active curve in exactly one Curve modifier."
    return geo, mods[0], ""


def _curve_usage_error(curve_obj):
    uses = [(obj, mod) for obj in bpy.data.objects for mod in obj.modifiers if str(getattr(mod, "type", "")) == "CURVE" and getattr(mod, "object", None) == curve_obj]
    return "" if len(uses) == 1 else "Active curve is shared by multiple Curve modifiers."


def _selected_split(curve_obj):
    spline, error = _single_spline(curve_obj)
    if error:
        return None, error
    if str(spline.type) == "BEZIER":
        return _selected_point_split(curve_obj, spline, _selected_bezier_ids(spline))
    if str(spline.type) == "POLY":
        return _selected_point_split(curve_obj, spline, _selected_poly_ids(spline))
    return None, "Only Bezier and Poly splines are supported."


def _single_spline(curve_obj):
    splines = tuple(getattr(getattr(curve_obj, "data", None), "splines", ()))
    if len(splines) != 1:
        return None, "Curve must contain exactly one spline."
    if bool(getattr(splines[0], "use_cyclic_u", False)):
        return None, "Cyclic curves are not supported."
    return splines[0], ""


def _selected_bezier_ids(spline):
    return [index for index, point in enumerate(spline.bezier_points) if point.select_control_point]


def _selected_poly_ids(spline):
    return [index for index, point in enumerate(spline.points) if point.select]


def _selected_point_split(curve_obj, spline, ids):
    points = _spline_points(spline)
    ids = tuple(sorted(ids))
    error = _split_selection_error(ids, len(points))
    if error:
        return None, error
    worlds = tuple(_point_world(curve_obj, points[idx].co) for idx in ids)
    return (0, ids, str(spline.type), worlds), ""


def _split_selection_error(ids, point_count):
    if not ids:
        return "Select one or more interior curve points."
    if ids[0] <= 0 or ids[-1] >= point_count - 1:
        return "Selected points must be interior points."
    return ""


def _spline_points(spline):
    return tuple(spline.bezier_points) if str(spline.type) == "BEZIER" else tuple(spline.points)


def _point_world(curve_obj, co):
    local = Vector((float(co[0]), float(co[1]), float(co[2])))
    return tuple(curve_obj.matrix_world @ local)


def _build_spec(root, scene, source_scp, parent_scp, curve_obj, geo, mod, split):
    spline_index, split_indices, spline_type, point_worlds = split
    return SplitCornerSpec(
        root, scene, str(source_scp.id or ""), str(source_scp.name or ""),
        str(source_scp.parent_id or ""), _scalar_payload(source_scp, _SCP_SKIP),
        snapshot_attachment_runtime(source_scp), _bound_snapshot(source_scp),
        curve_obj, getattr(source_scp, "transform_object_ref", None), geo,
        str(parent_scp.id or ""), mod.name, spline_index, split_indices,
        spline_type, point_worlds,
    )


def _split_segments(spec):
    spline = spec.curve_obj.data.splines[spec.spline_index]
    return _split_bezier_points(spline, spec.split_indices) if spec.spline_type == "BEZIER" else _split_poly_points(spline, spec.split_indices)


def _split_bezier_points(spline, split_indices):
    points = tuple(_bezier_point_data(point) for point in spline.bezier_points)
    segments = [list(segment) for segment in _point_segments(points, split_indices)]
    for index, segment in enumerate(segments):
        if index > 0:
            segment[0] = replace(segment[0], handle_left=segment[0].co, handle_left_type="FREE")
        if index < len(segments) - 1:
            segment[-1] = replace(segment[-1], handle_right=segment[-1].co, handle_right_type="FREE")
    return tuple(tuple(segment) for segment in segments)


def _split_poly_points(spline, split_indices):
    points = tuple(_poly_point_data(point) for point in spline.points)
    return _point_segments(points, split_indices)


def _point_segments(points, split_indices):
    ranges = _segment_ranges(len(points), split_indices)
    return tuple(tuple(points[start:end]) for start, end in ranges)


def _segment_ranges(point_count, split_indices):
    start, ranges = 0, []
    for index in split_indices:
        ranges.append((start, index + 1))
        start = index
    return (*ranges, (start, point_count))


def _clone_scps(spec, count):
    return tuple(_clone_scp(spec) for _ in range(count))


def _segment_objects(source, clones):
    return (source, *(obj_map[source] for _dst, obj_map in clones))


def _rewrite_segments(curves, segments):
    for curve, points in zip(curves, segments):
        _rewrite_curve(curve, points)


def _retarget_segments(geos, modifier_name, curves):
    for geo, curve in zip(geos, curves):
        _retarget_curve_object(geo, modifier_name, curve)


def _bezier_point_data(point):
    return BezierPointData(tuple(point.co), tuple(point.handle_left), tuple(point.handle_right), str(point.handle_left_type), str(point.handle_right_type), float(point.radius), float(point.tilt))


def _poly_point_data(point):
    return PolyPointData(tuple(point.co), float(point.radius), float(point.tilt))


def _clone_scp(spec):
    dst = create_scp(spec.root, spec.source_name)
    _apply_payload(dst, spec.source_scalars)
    obj_map, native = _clone_bound_objects(spec, dst)
    set_scp_transform_object(spec.root, dst, obj_map.get(spec.transform_obj))
    set_scp_geometry_object(spec.root, dst, obj_map.get(spec.geometry_obj))
    set_prop_raw(dst, "parent_id", spec.source_parent_id)
    restore_attachment_runtime(dst, spec.source_runtime)
    _restore_native_flags(spec.root, dst, native)
    return dst, obj_map


def _clone_bound_objects(spec, dst):
    obj_map, native = {}, []
    for obj, enabled in spec.bound_items:
        clone = _clone_object(spec.scene, obj)
        obj_map[obj], native = clone, [*native, (clone, enabled)]
        add_bound_object_to_scp(spec.root, dst, clone)
    remap_object_cluster_refs(obj_map)
    remap_object_cluster_parents(obj_map)
    return obj_map, tuple(native)


def _clone_object(scene, obj):
    clone = obj.copy()
    clone.data = None if getattr(obj, "data", None) is None else obj.data.copy()
    for col in tuple(getattr(obj, "users_collection", ()) or ()) or (scene.collection,):
        col.objects.link(clone)
    clear_scp_tags(clone), clear_scp_control_marks(clone), clear_native_parent_keep_world(clone)
    return clone


def _restore_native_flags(root, scp, flags):
    for obj, enabled in flags:
        entry = find_bound_entry_by_object(scp, obj)
        if entry is not None and not enabled:
            set_bound_native_parenting(root, scp, entry.id, False)


def _bound_snapshot(scp):
    return tuple((obj, bool(getattr(entry, "native_parenting_enabled", True))) for entry, obj in iter_bound_objects(scp))


def _copy_scalars(src, dst, skip=()):
    for key, value in _scalar_payload(src, skip):
        setattr(dst, key, value)


def _scalar_payload(owner, skip=()):
    return tuple((prop.identifier, getattr(owner, prop.identifier)) for prop in owner.bl_rna.properties if _copyable_prop(prop, skip))


def _copyable_prop(prop, skip=()):
    key = prop.identifier
    skip = set(skip or ())
    return key != "rna_type" and key not in skip and not prop.is_readonly and prop.type not in {"COLLECTION", "POINTER"}


def _rewrite_curve(curve_obj, points):
    spline = curve_obj.data.splines[0]
    spline_type, payload = str(spline.type), _scalar_payload(spline, {"bezier_points", "points"})
    _clear_splines(curve_obj.data)
    new_spline = curve_obj.data.splines.new(type=spline_type)
    _apply_payload(new_spline, payload)
    new_spline.use_cyclic_u = False
    _write_spline_points(new_spline, points)


def _clear_splines(curve):
    while curve.splines:
        curve.splines.remove(curve.splines[0])


def _apply_payload(owner, payload):
    for key, value in tuple(payload or ()):
        setattr(owner, key, value)


def _write_spline_points(spline, points):
    if str(spline.type) == "BEZIER":
        return _write_bezier_points(spline, points)
    return _write_poly_points(spline, points)


def _write_bezier_points(spline, points):
    if len(points) > 1:
        spline.bezier_points.add(len(points) - 1)
    for index, point in enumerate(points):
        _write_bezier_point(spline.bezier_points[index], point)


def _write_poly_points(spline, points):
    if len(points) > 1:
        spline.points.add(len(points) - 1)
    for index, point in enumerate(points):
        _write_poly_point(spline.points[index], point)


def _write_bezier_point(dst, point):
    dst.co = point.co
    dst.handle_left = point.handle_left
    dst.handle_right = point.handle_right
    dst.handle_left_type = point.handle_left_type
    dst.handle_right_type = point.handle_right_type
    dst.radius = point.radius
    dst.tilt = point.tilt


def _write_poly_point(dst, point):
    dst.co = point.co
    dst.radius = point.radius
    dst.tilt = point.tilt


def _retarget_curve_object(geo, modifier_name, curve_obj):
    mod = None if geo is None else geo.modifiers.get(modifier_name)
    if mod is not None:
        mod.object = curve_obj


def _create_controls(spec):
    return tuple(_create_control(spec, point_world) for point_world in spec.point_worlds)


def _create_control(spec, point_world):
    parent = find_scp_by_id(spec.root, spec.parent_scp_id)
    ctrl = bpy.data.objects.new(f"{spec.source_scp_id}_CORNER", None)
    _host_collection(spec.scene, spec.root).objects.link(ctrl)
    ctrl.empty_display_type, ctrl.empty_display_size = "PLAIN_AXES", 0.1
    _set_world_location(ctrl, point_world)
    add_bound_object_to_scp(spec.root, parent, ctrl)
    sync_scp_roles(spec.root, parent)
    _set_world_location(ctrl, point_world)
    return mark_scp_control_object(ctrl, spec.root, parent.id)


def _host_collection(scene, root):
    cols = tuple(getattr(root, "users_collection", ()) or ())
    return cols[0] if cols else scene.collection


def _set_world_location(obj, location):
    world = obj.matrix_world.copy()
    world.translation = Vector(location)
    obj.matrix_world = world


def _bind_segment_hooks(curves, segments, ctrls, spline_type):
    for index, (curve, points) in enumerate(zip(curves, segments)):
        _bind_segment_ends(curve, points, index, ctrls, spline_type)


def _bind_segment_ends(curve_obj, points, index, ctrls, spline_type):
    if index > 0:
        _bind_split_hook(curve_obj, points, 0, ctrls[index - 1], spline_type)
    if index < len(ctrls):
        _bind_split_hook(curve_obj, points, len(points) - 1, ctrls[index], spline_type)


def _bind_split_hook(curve_obj, points, point_index, ctrl, spline_type):
    local = _local_point(points[point_index].co)
    hook = curve_obj.modifiers.new("Split Corner Hook", "HOOK")
    hook.object, hook.center = ctrl, local
    hook.matrix_inverse = Matrix.Translation(-local)
    hook.vertex_indices_set(_hook_indices(spline_type, point_index))


def _local_point(co):
    return Vector((float(co[0]), float(co[1]), float(co[2])))


def _hook_indices(spline_type, point_index):
    if spline_type == "BEZIER":
        base = point_index * 3
        return (base, base + 1, base + 2)
    return (point_index,)


def _select_control(context, ctrl):
    for obj in tuple(getattr(context, "selected_objects", ()) or ()):
        obj.select_set(False)
    ctrl.select_set(True)
    context.view_layer.objects.active = ctrl
