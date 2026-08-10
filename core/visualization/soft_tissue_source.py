from dataclasses import dataclass
import json
import math

import bmesh
from mathutils import Vector
from mathutils.geometry import interpolate_bezier

from ..scp_proxy.signature import mesh_topology_signature, open_evaluated_mesh
from ..scp_runtime.common import find_geometry_mesh_scp_obj
from ..utils import depsgraph_for_scene
from ..vcp.attachment_backend import (
    attachment_runtime, capture_attachment_from_world, resolve_attachment_normal,
    resolve_attachment_basis, resolve_attachment_world,
)
from ..vcp.soft_tissue_surface_field import boundary_edges, boundary_falloff_weights


@dataclass(frozen=True)
class BaseSample:
    points: tuple
    normals: tuple
    faces: tuple = ()
    boundary_edges: tuple = ()
    weights: tuple = ()
    cyclic: bool = False
    groups: dict = None


def infer_base_domain(obj):
    kind = "" if obj is None else str(getattr(obj, "type", ""))
    return {"EMPTY": "POINT", "CURVE": "CURVE", "MESH": "SURFACE"}.get(kind, "")


def host_object(root, scene, tissue):
    target = str(getattr(tissue, "host_scp_id", "") or "")
    return None if not target else find_geometry_mesh_scp_obj(scene, root.name, target)


def host_signature(obj, scene=None):
    if obj is None:
        return ""
    evaluated, mesh = open_evaluated_mesh(scene, obj, refresh=False)
    try:
        return "" if mesh is None else mesh_topology_signature(mesh)
    finally:
        None if evaluated is None else evaluated.to_mesh_clear()


def validate_source(obj, domain):
    if obj is None:
        return ("Missing base object.",)
    errors = [] if infer_base_domain(obj) == str(domain) else ["Base object type does not match its domain."]
    errors += _curve_errors(obj) if str(domain) == "CURVE" else []
    errors += _surface_errors(obj) if str(domain) == "SURFACE" else []
    return tuple(errors)


def sample_base(obj, tissue, resolved=None, scene=None):
    domain = str(tissue.base_domain)
    if domain == "POINT":
        return _point_sample(obj, resolved)
    if domain == "CURVE":
        return _curve_sample(obj, tissue, resolved, scene)
    return _surface_sample(obj, tissue, resolved, scene)


def capture_sample_bindings(root, scene, tissue, sample):
    runtime = attachment_runtime(scene)
    values = [capture_attachment_from_world(root, scene, tissue.host_scp_id, Vector(point), runtime)
              for point in sample.points]
    if any(value is None for value in values):
        raise ValueError("Could not bind every base sample to the host SCP.")
    return _json_payload(values)


def resolve_sample_bindings(root, scene, tissue):
    values = _json_list(tissue.base_bindings_json)
    runtime = attachment_runtime(scene)
    points = [resolve_attachment_world(root, scene, tissue.host_scp_id, raw, runtime) for raw in values]
    normals = [resolve_attachment_normal(root, scene, tissue.host_scp_id, raw, runtime) for raw in values]
    if any(value is None for value in points + normals):
        raise ValueError("Stored base bindings no longer resolve.")
    return tuple(tuple(value) for value in points), tuple(tuple(value) for value in normals)


def capture_control_bindings(root, scene, tissue):
    obj = tissue.base_object_ref
    runtime = attachment_runtime(scene)
    values = [_capture_control_row(root, scene, tissue, obj, index, point, runtime)
              for index, point in enumerate(_control_world_points(obj))]
    if any(value is None for value in values):
        raise ValueError("Could not bind every base control to the host SCP.")
    return _json_payload(values)


def apply_control_bindings(root, scene, tissue):
    obj = tissue.base_object_ref
    values = _json_list(tissue.control_bindings_json)
    runtime = attachment_runtime(scene)
    points = [resolve_attachment_world(root, scene, tissue.host_scp_id, _row_raw(raw), runtime) for raw in values]
    if any(point is None for point in points) or len(points) != len(_control_world_points(obj)):
        raise ValueError("Stored base control bindings no longer resolve.")
    _write_control_world_points(obj, points)
    _restore_bezier_handles(root, scene, tissue, obj, values, runtime)


def _capture_control_row(root, scene, tissue, obj, index, point, runtime):
    raw = capture_attachment_from_world(root, scene, tissue.host_scp_id, point, runtime)
    if raw is None:
        return None
    row = {"raw": raw}
    control = _control_at(obj, index)
    if control is not None and hasattr(control, "handle_left"):
        basis = resolve_attachment_basis(root, scene, tissue.host_scp_id, raw, runtime)
        row.update(_handle_payload(obj, control, point, basis))
    return row


def _handle_payload(obj, control, point, basis):
    if basis is None:
        return {}
    left = obj.matrix_world @ control.handle_left - Vector(point)
    right = obj.matrix_world @ control.handle_right - Vector(point)
    inverse = basis.transposed()
    return {"handle_left": tuple(inverse @ left), "handle_right": tuple(inverse @ right)}


def _restore_bezier_handles(root, scene, tissue, obj, values, runtime):
    if obj.type != "CURVE" or obj.data.splines[0].type != "BEZIER":
        return
    inverse = obj.matrix_world.inverted()
    for control, row in zip(obj.data.splines[0].bezier_points, values):
        _restore_one_handle(root, scene, tissue, control, row, runtime, inverse)


def _restore_one_handle(root, scene, tissue, control, row, runtime, inverse):
    basis = resolve_attachment_basis(root, scene, tissue.host_scp_id, _row_raw(row), runtime)
    if basis is None or "handle_left" not in row:
        return
    center = Vector(control.co)
    control.handle_left = inverse @ (inverse.inverted() @ center + basis @ Vector(row["handle_left"]))
    control.handle_right = inverse @ (inverse.inverted() @ center + basis @ Vector(row["handle_right"]))


def _control_at(obj, index):
    controls = _curve_controls(obj) if obj.type == "CURVE" else ()
    return controls[index] if 0 <= int(index) < len(controls) else None


def _row_raw(row):
    return row.get("raw", "") if isinstance(row, dict) else row


def _point_sample(obj, resolved):
    point = tuple(obj.matrix_world.translation) if resolved is None else tuple(resolved[0][0])
    return BaseSample((point,), ((0.0, 0.0, 1.0),))


def _curve_sample(obj, tissue, resolved, scene):
    points, cyclic = _curve_world_points(obj, int(tissue.base_resolution), scene)
    normals = tuple(_default_normal(obj) for _ in points)
    if resolved is not None:
        points, normals = resolved
    return BaseSample(tuple(points), tuple(normals), cyclic=cyclic)


def _surface_sample(obj, tissue, resolved, scene):
    evaluated, mesh = open_evaluated_mesh(scene, obj, refresh=False)
    try:
        owner, data = evaluated or obj, mesh or obj.data
        if _surface_needs_refinement(data):
            return _refined_surface_sample(obj, owner, data, tissue, resolved)
        return _surface_sample_from_mesh(obj, owner, data, tissue, resolved)
    finally:
        None if evaluated is None else evaluated.to_mesh_clear()


def _surface_needs_refinement(mesh):
    edges, faces = _mesh_topology(mesh)
    boundary = boundary_edges(edges, faces)
    indices = {index for edge in boundary for index in edge}
    return bool(boundary and len(indices) == len(mesh.vertices))


def _mesh_topology(mesh):
    edges = tuple(tuple(edge.vertices) for edge in mesh.edges)
    faces = tuple(tuple(poly.vertices) for poly in mesh.polygons)
    return edges, faces


def _refined_surface_sample(source, evaluated, mesh, tissue, resolved):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        cuts = max(1, min(32, int(tissue.base_resolution) - 2))
        bmesh.ops.subdivide_edges(bm, edges=tuple(bm.edges), cuts=cuts, use_grid_fill=True)
        return _surface_sample_from_bmesh(source, evaluated, bm, tissue, resolved)
    finally:
        bm.free()


def _surface_sample_from_bmesh(source, evaluated, bm, tissue, resolved):
    bm.normal_update()
    _index_bmesh(bm)
    points = tuple(tuple(evaluated.matrix_world @ vertex.co) for vertex in bm.verts)
    normals = tuple(tuple(_world_normal(evaluated, vertex.normal)) for vertex in bm.verts)
    points = points if resolved is None else resolved[0]
    edges = tuple(tuple(vertex.index for vertex in edge.verts) for edge in bm.edges)
    faces = tuple(tuple(vertex.index for vertex in face.verts) for face in bm.faces)
    bounds = boundary_edges(edges, faces)
    weights = _refined_field_weights(source, bm, tissue.field_attribute, points, edges, faces)
    groups = _refined_custom_groups(source, bm, tissue)
    return BaseSample(tuple(points), normals, faces, bounds, weights, False, groups)


def _index_bmesh(bm):
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()


def _refined_field_weights(source, bm, name, points, edges, faces):
    values = _bmesh_group_weights(source, bm, name)
    if _generated_surface_field(source, name):
        return boundary_falloff_weights(len(points), edges, faces, points)
    return values


def _generated_surface_field(source, name):
    values = _group_weights(source, name)
    return source.vertex_groups.get(str(name or "")) is None or not any(value > 1.0e-8 for value in values)


def _refined_custom_groups(source, bm, tissue):
    return {name: _bmesh_group_weights(source, bm, name) for name in _custom_group_names(tissue)
            if source.vertex_groups.get(name) is not None}


def _bmesh_group_weights(source, bm, name):
    group = source.vertex_groups.get(str(name or ""))
    layer = bm.verts.layers.deform.active
    if group is None:
        return tuple(1.0 for _ in bm.verts)
    if layer is None:
        return tuple(0.0 for _ in bm.verts)
    return tuple(float(vertex[layer].get(group.index, 0.0)) for vertex in bm.verts)


def _surface_sample_from_mesh(source, evaluated, mesh, tissue, resolved):
    points = tuple(tuple(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices)
    normals = tuple(tuple(_world_normal(evaluated, vertex.normal)) for vertex in mesh.vertices)
    if resolved is not None:
        points = resolved[0]
    faces = tuple(tuple(poly.vertices) for poly in mesh.polygons)
    edges = tuple(tuple(edge.vertices) for edge in mesh.edges)
    weights = _group_weights(source, tissue.field_attribute)
    groups = _custom_groups(source, tissue)
    return BaseSample(tuple(points), tuple(normals), faces, boundary_edges(edges, faces), weights, False, groups)


def _custom_groups(obj, tissue):
    names = _custom_group_names(tissue)
    return {name: _group_weights(obj, name) for name in names if obj.vertex_groups.get(name) is not None}


def _custom_group_names(tissue):
    semantic = {"ALL", "BACKING", "BOUNDARY", "ENDPOINTS", "SUSPENSION"}
    return {str(row.mask_attribute) for row in tissue.attachments
            if str(row.mask_attribute).upper() not in semantic}


def _curve_world_points(obj, resolution, scene=None):
    evaluated = obj.evaluated_get(depsgraph_for_scene(scene)) if scene is not None else obj
    spline = evaluated.data.splines[0]
    local = _bezier_points(spline, resolution) if spline.type == "BEZIER" else _spline_points(spline)
    cyclic = bool(spline.use_cyclic_u)
    sampled = _resample_curve(local, int(resolution), cyclic)
    return tuple(tuple(evaluated.matrix_world @ point) for point in sampled), cyclic


def _resample_curve(points, resolution, cyclic):
    values = [Vector(point) for point in points]
    if cyclic and len(values) > 1 and (values[0] - values[-1]).length <= 1.0e-9:
        values.pop()
    pairs = _curve_pairs(len(values), cyclic)
    lengths = [(values[b] - values[a]).length for a, b in pairs]
    total = sum(lengths)
    count = max(3 if cyclic else 2, int(resolution))
    targets = [total * i / (count if cyclic else count - 1) for i in range(count)]
    return tuple(_point_at_distance(values, pairs, lengths, target) for target in targets)


def _point_at_distance(points, pairs, lengths, target):
    passed = 0.0
    for (first, second), length in zip(pairs, lengths):
        if target <= passed + length or length <= 1.0e-12:
            factor = 0.0 if length <= 1.0e-12 else (target - passed) / length
            return points[first].lerp(points[second], max(0.0, min(1.0, factor)))
        passed += length
    return points[-1].copy()


def _bezier_points(spline, resolution):
    controls = tuple(spline.bezier_points)
    pairs = _curve_pairs(len(controls), bool(spline.use_cyclic_u))
    steps = max(2, math.ceil(int(resolution) / max(1, len(pairs))))
    segments = [interpolate_bezier(controls[a].co, controls[a].handle_right,
                                   controls[b].handle_left, controls[b].co, steps)
                for a, b in pairs]
    return tuple(point.copy() for index, values in enumerate(segments)
                 for point in (values if index == 0 else values[1:]))


def _spline_points(spline):
    points = tuple(getattr(spline, "evaluated_points", ()) or ()) or tuple(spline.points)
    return tuple(Vector(point.co[:3]) for point in points)


def _curve_pairs(count, cyclic):
    values = [(index, index + 1) for index in range(count - 1)]
    return tuple(values + ([(count - 1, 0)] if cyclic else []))


def _curve_errors(obj):
    splines = () if obj is None or obj.type != "CURVE" else tuple(obj.data.splines)
    if len(splines) != 1:
        return ["Curve base must contain exactly one spline."]
    count = len(splines[0].bezier_points) if splines[0].type == "BEZIER" else len(splines[0].points)
    errors = [] if count >= 2 else ["Curve base requires at least two control points."]
    errors += [] if count < 2 or _curve_has_span(obj) else ["Curve base must have non-zero length."]
    return errors


def _curve_has_span(obj):
    controls = _curve_controls(obj)
    origin = Vector(controls[0].co[:3])
    return any((Vector(point.co[:3]) - origin).length > 1.0e-9 for point in controls[1:])


def _surface_errors(obj):
    if obj is None or obj.type != "MESH":
        return []
    mesh = obj.data
    errors = [] if mesh.polygons else ["Surface base requires faces."]
    errors += [] if _one_component(mesh) else ["Surface base must contain one connected component."]
    errors += [] if _manifold_edges(mesh) else ["Surface base contains loose or non-manifold edges."]
    errors += [] if _basis_shape_active(obj) else ["Activate the Basis shape key before using this surface."]
    errors += [] if not _topology_modifiers(obj) else ["Surface base has a topology-changing modifier."]
    return errors


def _basis_shape_active(obj):
    keys = getattr(obj.data, "shape_keys", None)
    return keys is None or int(getattr(obj, "active_shape_key_index", 0)) == 0


def _topology_modifiers(obj):
    deformers = {"ARMATURE", "CAST", "CURVE", "DISPLACE", "HOOK", "LAPLACIANDEFORM", "LATTICE",
                 "MESH_DEFORM", "SHRINKWRAP", "SIMPLE_DEFORM", "SMOOTH", "LAPLACIANSMOOTH",
                 "CORRECTIVE_SMOOTH", "SURFACE_DEFORM", "WARP", "WAVE"}
    return tuple(modifier for modifier in obj.modifiers if modifier.show_viewport and modifier.type not in deformers)


def _one_component(mesh):
    if not mesh.vertices:
        return False
    graph = _mesh_adjacency(mesh)
    seen, queue = {0}, [0]
    while queue:
        for value in graph[queue.pop()] - seen:
            seen.add(value)
            queue.append(value)
    return len(seen) == len(mesh.vertices)


def _mesh_adjacency(mesh):
    graph = [set() for _ in mesh.vertices]
    for edge in mesh.edges:
        first, second = tuple(edge.vertices)
        graph[first].add(second)
        graph[second].add(first)
    return graph


def _manifold_edges(mesh):
    counts = {tuple(sorted(edge.vertices)): 0 for edge in mesh.edges}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            counts[tuple(sorted(key))] = counts.get(tuple(sorted(key)), 0) + 1
    return bool(counts) and all(value in {1, 2} for value in counts.values())


def _group_weights(obj, name):
    group = obj.vertex_groups.get(str(name or ""))
    if group is None:
        return tuple(1.0 for _ in obj.data.vertices)
    return tuple(_vertex_weight(group, vertex.index) for vertex in obj.data.vertices)


def _vertex_weight(group, index):
    try:
        return float(group.weight(index))
    except RuntimeError:
        return 0.0


def _control_world_points(obj):
    if obj.type == "EMPTY":
        return (obj.matrix_world.translation.copy(),)
    if obj.type == "MESH":
        return tuple(obj.matrix_world @ vertex.co for vertex in obj.data.vertices)
    return tuple(obj.matrix_world @ Vector(point.co[:3]) for point in _curve_controls(obj))


def _curve_controls(obj):
    spline = obj.data.splines[0]
    return tuple(spline.bezier_points) if spline.type == "BEZIER" else tuple(spline.points)


def _write_control_world_points(obj, points):
    if obj.type == "EMPTY":
        obj.location = points[0]
        return
    inverse = obj.matrix_world.inverted()
    controls = tuple(obj.data.vertices) if obj.type == "MESH" else _curve_controls(obj)
    for control, world in zip(controls, points):
        _move_control(control, inverse @ world)
    _update_source_data(obj)


def _update_source_data(obj):
    updater = getattr(obj.data, "update", None)
    if callable(updater):
        updater()
    else:
        obj.data.update_tag()


def _move_control(control, local):
    old = Vector(control.co[:3])
    delta = Vector(local) - old
    control.co = (*local, control.co[3]) if len(control.co) == 4 else local
    if hasattr(control, "handle_left"):
        control.handle_left += delta
        control.handle_right += delta


def _default_normal(obj):
    return tuple(_world_normal(obj, Vector((0.0, 0.0, 1.0))))


def _world_normal(obj, normal):
    value = obj.matrix_world.to_3x3().inverted().transposed() @ Vector(normal)
    return value.normalized() if value.length > 1.0e-12 else Vector((0.0, 0.0, 1.0))


def _json_list(raw):
    try:
        value = json.loads(str(raw or "[]"))
    except Exception:
        value = []
    if isinstance(value, dict):
        value = value.get("bindings", [])
    return list(value) if isinstance(value, list) else []


def _json_payload(values):
    return json.dumps({"version": 1, "bindings": values}, separators=(",", ":"))
