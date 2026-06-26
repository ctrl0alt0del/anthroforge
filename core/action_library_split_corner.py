from dataclasses import dataclass, replace

import bpy
from mathutils import Matrix, Vector

from .scp_runtime.bound_objects import clear_scp_tags, find_bound_entry_by_object, iter_bound_objects, set_bound_native_parenting, sync_scp_roles
from .scp_runtime.common import find_scp_by_id, scp_for_object, set_prop_raw
from .scp_runtime.lookup import clear_native_parent_keep_world
from .scp_runtime.object_roles import add_bound_object_to_scp, create_scp, set_scp_geometry_object, set_scp_transform_object
from .scp_runtime.prop_update_guard import set_parent_id_raw
from .scp_runtime.runtime_state import mirror_status, restore_attachment_runtime, snapshot_attachment_runtime
from .utils import get_af_root, scene_for_id, update_scene_view_layer
from .visualization.mirror_objects import remap_object_cluster_parents, remap_object_cluster_refs
from .visualization.scp_control_helpers import clear_scp_control_marks, mark_scp_control_object

_SCP_SKIP = {"id", "name", "parent_id", "color", "bound_objects", "transform_object_ref", "geometry_object_ref", "color_initialized"}


@dataclass(frozen=True)
class SplitCornerSpec:
    root: object
    scene: object
    source_scp_id: str
    source_name: str
    source_parent_id: str
    source_scalars: tuple
    source_color: tuple
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
    return (None, error) if error else _run_split_corner(context, spec)


def _run_split_corner(context, spec):
    bpy.ops.object.mode_set(mode="OBJECT")
    segments = _split_segments(spec)
    refs = _split_reference_frames(spec)
    clones = _clone_scps(spec, len(segments) - 1)
    curves, geos = _split_objects(spec, clones)
    _rewrite_segments(curves, segments)
    _apply_tilt_offsets(curves, _segment_tilt_offsets(spec, curves, refs))
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
    parent_scp = find_scp_by_id(root, getattr(source_scp, "parent_id", ""))
    error = _spec_error(source_scp, curve_obj, parent_scp)
    if error:
        return None, error
    geo, mod, error = _geometry_target(source_scp, curve_obj)
    if error:
        return None, error
    return _validated_split(root, context, source_scp, parent_scp, curve_obj, geo, mod)


def _spec_error(source_scp, curve_obj, parent_scp):
    return _source_error(source_scp, curve_obj) or _parent_error(source_scp, parent_scp)


def _validated_split(root, context, source_scp, parent_scp, curve_obj, geo, mod):
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
        str(source_scp.parent_id or ""), _scalar_payload(source_scp, _SCP_SKIP), _source_color(source_scp),
        snapshot_attachment_runtime(source_scp), _bound_snapshot(source_scp),
        curve_obj, getattr(source_scp, "transform_object_ref", None), geo,
        str(parent_scp.id or ""), mod.name, spline_index, split_indices,
        spline_type, point_worlds,
    )


def _source_color(scp):
    obj = _source_color_obj(scp)
    return _object_color(obj) if obj is not None else _object_color(scp)


def _source_color_obj(scp):
    refs = (getattr(scp, "geometry_object_ref", None), getattr(scp, "transform_object_ref", None))
    return next((obj for obj in refs if obj is not None), next((obj for _entry, obj in iter_bound_objects(scp)), None))


def _object_color(obj):
    color = tuple(getattr(obj, "color", (0.0, 0.0, 0.0, 1.0)) or ())
    return tuple(float(v) for v in color[:4]) if len(color) >= 4 else (0.0, 0.0, 0.0, 1.0)


def _split_segments(spec):
    spline = spec.curve_obj.data.splines[spec.spline_index]
    return _split_bezier_points(spline, spec.split_indices) if spec.spline_type == "BEZIER" else _split_poly_points(spline, spec.split_indices)


def _split_reference_frames(spec):
    if not _needs_tilt_compensation(spec.curve_obj):
        return ()
    factors = _split_factors(spec)
    axis = _forward_axis(spec)
    return tuple(_curve_frame(spec.scene, spec.curve_obj, factor, axis) for factor in factors)


def _needs_tilt_compensation(curve_obj):
    data = getattr(curve_obj, "data", None)
    mode = str(getattr(data, "twist_mode", "MINIMUM") or "MINIMUM").upper()
    return mode in {"MINIMUM", "MINIMUM_TWIST"}


def _split_factors(spec):
    spline = spec.curve_obj.data.splines[spec.spline_index]
    samples = _world_samples(spec.curve_obj, _spline_points(spline), spec.spline_type)
    lengths = _cumulative_lengths(samples)
    return tuple(_nearest_factor(samples, lengths, Vector(point_world)) for point_world in spec.point_worlds)


def _world_samples(curve_obj, points, spline_type):
    samples, _cmap = _sampled_points(points, spline_type, _sample_steps(curve_obj))
    return tuple(curve_obj.matrix_world @ point for point in samples)


def _sample_steps(curve_obj):
    data = getattr(curve_obj, "data", None)
    return max(12, int(getattr(data, "resolution_u", 12) or 12))


def _cumulative_lengths(samples):
    total, lengths = 0.0, [0.0]
    for a, b in zip(samples, samples[1:]):
        total += (b - a).length
        lengths.append(total)
    return tuple(lengths)


def _nearest_factor(samples, lengths, world_point):
    index = min(range(len(samples)), key=lambda idx: (samples[idx] - world_point).length_squared)
    total = lengths[-1] if lengths else 0.0
    return 0.0 if total <= 1.0e-9 else lengths[index] / total


def _segment_tilt_offsets(spec, curves, refs):
    axis = _forward_axis(spec)
    return tuple(_segment_tilt_offset(spec.scene, curve, index, refs, axis) for index, curve in enumerate(curves))


def _segment_tilt_offset(scene, curve_obj, index, refs, axis):
    if index <= 0 or index > len(refs):
        return 0.0
    tangent, normal = _curve_frame(scene, curve_obj, 0.0, axis)
    ref_tangent, ref_normal = refs[index - 1]
    return _roll_delta(normal, ref_normal, tangent if tangent.length > 1.0e-9 else ref_tangent)


def _curve_frame(scene, curve_obj, factor, forward_axis):
    probe, use_path = _curve_probe(scene, curve_obj, forward_axis)
    try:
        probe.constraints[0].offset_factor = max(0.0, min(1.0, float(factor)))
        update_scene_view_layer(scene or scene_for_id(curve_obj) or scene_for_id(probe))
        return _probe_axes(probe, forward_axis)
    finally:
        _clear_curve_probe(probe, curve_obj, use_path)


def _curve_probe(scene, curve_obj, forward_axis):
    probe = bpy.data.objects.new(f"{curve_obj.name}_AF_SPLIT_PROBE", None)
    scene.collection.objects.link(probe)
    use_path = bool(getattr(curve_obj.data, "use_path", False))
    curve_obj.data.use_path = True
    _configure_curve_probe(probe.constraints.new("FOLLOW_PATH"), curve_obj, forward_axis)
    return probe, use_path


def _configure_curve_probe(constraint, curve_obj, forward_axis):
    constraint.target = curve_obj
    constraint.use_curve_follow = True
    constraint.use_fixed_location = True
    constraint.forward_axis = forward_axis
    constraint.up_axis = _up_axis(forward_axis)


def _clear_curve_probe(probe, curve_obj, use_path):
    curve_obj.data.use_path = use_path
    bpy.data.objects.remove(probe, do_unlink=True)


def _probe_axes(probe, forward_axis):
    basis = probe.matrix_world.to_3x3()
    tangent = basis @ _local_axis(forward_axis)
    normal = basis @ _local_axis(_up_axis(forward_axis))
    return tangent.normalized(), normal.normalized()


def _forward_axis(spec):
    mod = None if spec.geometry_obj is None else spec.geometry_obj.modifiers.get(spec.modifier_name)
    axis = str(getattr(mod, "deform_axis", "POS_X") or "POS_X")
    return {"POS_X": "FORWARD_X", "POS_Y": "FORWARD_Y", "POS_Z": "FORWARD_Z", "NEG_X": "TRACK_NEGATIVE_X", "NEG_Y": "TRACK_NEGATIVE_Y", "NEG_Z": "TRACK_NEGATIVE_Z"}.get(axis, "FORWARD_X")


def _up_axis(forward_axis):
    return "UP_Y" if str(forward_axis).endswith("Z") else "UP_Z"


def _sampled_points(points, spline_type, steps):
    return _sample_bezier_points(points, steps) if spline_type == "BEZIER" else _sample_poly_points(points)


def _sample_poly_points(points):
    samples = tuple(_co_vec(point.co) for point in points)
    return samples, tuple(range(len(samples)))


def _sample_bezier_points(points, steps):
    samples, cmap = [_co_vec(points[0].co)], [0]
    for index in range(len(points) - 1):
        samples.extend(_bezier_segment_points(points[index], points[index + 1], steps)[1:])
        cmap.append(len(samples) - 1)
    return tuple(samples), tuple(cmap)


def _bezier_segment_points(a, b, steps):
    vals = (_co_vec(a.co), _co_vec(a.handle_right), _co_vec(b.handle_left), _co_vec(b.co))
    return [_bezier_point(*vals, step / float(steps)) for step in range(steps + 1)]


def _bezier_point(a, b, c, d, t):
    omt = 1.0 - t
    return (omt ** 3) * a + (3.0 * omt * omt * t) * b + (3.0 * omt * t * t) * c + (t ** 3) * d


def _co_vec(co):
    return Vector((float(co[0]), float(co[1]), float(co[2])))


def _project_vector(vec, tangent):
    return vec - tangent * vec.dot(tangent)


def _local_axis(axis_name):
    return {
        "FORWARD_X": Vector((1, 0, 0)), "FORWARD_Y": Vector((0, 1, 0)), "FORWARD_Z": Vector((0, 0, 1)),
        "TRACK_NEGATIVE_X": Vector((-1, 0, 0)), "TRACK_NEGATIVE_Y": Vector((0, -1, 0)), "TRACK_NEGATIVE_Z": Vector((0, 0, -1)),
        "UP_X": Vector((1, 0, 0)), "UP_Y": Vector((0, 1, 0)), "UP_Z": Vector((0, 0, 1)),
    }.get(str(axis_name), Vector((1, 0, 0)))


def _roll_delta(current, target, tangent):
    cur = _project_vector(current, tangent)
    tgt = _project_vector(target, tangent)
    if cur.length <= 1.0e-9 or tgt.length <= 1.0e-9:
        return 0.0
    cur, tgt = cur.normalized(), tgt.normalized()
    sign = 1.0 if tangent.dot(cur.cross(tgt)) >= 0.0 else -1.0
    return cur.angle(tgt) * sign


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


def _split_objects(spec, clones):
    return _segment_objects(spec.curve_obj, clones), _segment_objects(spec.geometry_obj, clones)


def _rewrite_segments(curves, segments):
    for curve, points in zip(curves, segments):
        _rewrite_curve(curve, points)


def _apply_tilt_offsets(curves, offsets):
    for curve, offset in zip(curves, offsets):
        _offset_curve_tilt(curve, offset)


def _offset_curve_tilt(curve_obj, offset):
    if abs(float(offset)) <= 1.0e-9:
        return
    for point in _spline_points(curve_obj.data.splines[0]):
        point.tilt = float(point.tilt) + float(offset)


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
    set_parent_id_raw(dst, spec.source_parent_id)
    restore_attachment_runtime(dst, spec.source_runtime)
    _restore_native_flags(spec.root, dst, native)
    _restore_scp_color(spec.root, dst, spec.source_color)
    return dst, obj_map


def _restore_scp_color(root, scp, color):
    set_prop_raw(scp, "color", color)
    set_prop_raw(scp, "color_initialized", True)
    sync_scp_roles(root, scp)


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
