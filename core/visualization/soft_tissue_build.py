from dataclasses import dataclass
import json
from types import SimpleNamespace

from mathutils import Vector

from ..vcp.blob_solver import BlobSolver
from ..vcp.soft_tissue_curve_inflation import (
    CurveRidgeProfile, backing_vertex_indices as curve_backing,
    commissure_vertex_indices, geometric_curve_relaxation, inflate_curve_ridge,
)
from ..vcp.soft_tissue_static_pouch import (
    StaticPouchSettings, StaticTether, gravity_step_from_sagginess, solve_static_tissue,
)
from ..vcp.soft_tissue_surface_inflation import (
    SurfaceLayerProfile, backing_vertex_indices as surface_backing,
    inflate_surface_layer, perimeter_vertex_indices,
)
from ..vcp.soft_tissue_surface_pipeline import GeometricRelaxationSpec, SurfaceTissuePipelineSpec, run_surface_tissue_pipeline
from .blob_sync_helpers import unit_local_mesh


@dataclass(frozen=True)
class RestShape:
    vertices: tuple
    faces: tuple
    groups: dict


@dataclass(frozen=True)
class FinalShape:
    vertices: tuple
    iterations: int = 0
    max_displacement: float = 0.0


def build_rest_shape(tissue, sample):
    if str(tissue.base_domain) == "POINT":
        return _point_rest(tissue, sample)
    if str(tissue.base_domain) == "CURVE":
        return _curve_rest(tissue, sample)
    return _surface_rest(tissue, sample)


def relax_shape(tissue, rest, target_obj=None, anchors=()):
    mode = str(tissue.relaxation_mode)
    if mode == "NONE":
        return FinalShape(rest.vertices)
    if mode == "GEOMETRIC":
        return _geometric_shape(tissue, rest, target_obj)
    return _static_shape(tissue, rest, anchors)


def capture_attachment_payload(root, scene, tissue, rest, capture_fn):
    runtime = _attachment_runtime(scene)
    for attachment in tissue.attachments:
        indices = rest.groups.get(str(attachment.mask_attribute).upper(), ())
        values = [_captured_row(root, scene, tissue, rest, index, runtime, capture_fn) for index in indices]
        attachment.bindings_json = json.dumps({"version": 1, "bindings": values}, separators=(",", ":"))


def resolve_attachment_anchors(root, scene, tissue, rest, point_fn, normal_fn):
    rows = []
    runtime = _attachment_runtime(scene)
    for attachment in tissue.attachments:
        rows += _resolved_attachment(root, scene, tissue, rest, attachment, runtime, point_fn, normal_fn)
    return tuple(rows)


def _point_rest(tissue, sample):
    unit, faces = unit_local_mesh(SimpleNamespace(resolution=int(tissue.base_resolution)))
    center = Vector(sample.points[0])
    scale = Vector(tissue.axis_scale) * float(tissue.inflation_amount)
    points = tuple(tuple(center + Vector((value.x * scale.x, value.y * scale.y, value.z * scale.z))) for value in unit)
    return RestShape(points, tuple(faces), {"ALL": tuple(range(len(points)))})


def _curve_rest(tissue, sample):
    profile = CurveRidgeProfile(
        float(tissue.profile_width), float(tissue.inflation_amount), float(tissue.profile_power),
        int(tissue.profile_segments), float(tissue.endpoint_taper), bool(sample.cyclic),
    )
    mesh = inflate_curve_ridge(sample.points, sample.normals, profile)
    groups = {"ALL": tuple(range(len(mesh.vertices))), "BACKING": curve_backing(mesh),
              "ENDPOINTS": () if sample.cyclic else commissure_vertex_indices(mesh)}
    return RestShape(mesh.vertices, mesh.faces, groups)


def _surface_rest(tissue, sample):
    profile = SurfaceLayerProfile(float(tissue.inflation_amount), float(tissue.minimum_amount), float(tissue.field_power))
    mesh = inflate_surface_layer(sample.points, sample.normals, sample.faces,
                                 sample.boundary_edges, sample.weights, profile)
    boundary = perimeter_vertex_indices(mesh, sample.boundary_edges)
    suspension = _suspension_indices(sample.weights)
    groups = {"ALL": tuple(range(len(mesh.vertices))), "BACKING": surface_backing(mesh),
              "BOUNDARY": boundary, "SUSPENSION": suspension}
    groups.update(_mapped_surface_groups(sample.groups, mesh.base_vertex_count))
    return RestShape(mesh.vertices, mesh.faces, groups)


def _mapped_surface_groups(groups, count):
    out = {}
    for name, weights in dict(groups or {}).items():
        base = [index for index, weight in enumerate(weights) if float(weight) > 0.0]
        out[str(name).upper()] = tuple(base + [int(count) + index for index in base])
    return out


def _geometric_shape(tissue, rest, target_obj):
    if str(tissue.base_domain) == "POINT":
        return _geometric_point(tissue, rest, target_obj)
    if str(tissue.base_domain) == "CURVE":
        fixed = _fixed_indices(tissue, rest)
        vertices = geometric_curve_relaxation(_curve_mesh(rest), tissue.sagginess,
                                              tissue.gravity, fixed, tissue.sag_limit,
                                              tissue.inflation_amount)
        return FinalShape(vertices)
    return FinalShape(_geometric_surface(tissue, rest))


def _geometric_point(tissue, rest, target_obj):
    runtime = _blob_runtime(tissue)
    points = [Vector(value) for value in rest.vertices]
    result = BlobSolver().solve(runtime, target_obj, points, rest.faces)
    return FinalShape(tuple(tuple(value) for value in result.points), result.iterations_used, result.max_disp)


def _geometric_surface(tissue, rest):
    count = len(rest.groups.get("BACKING", ()))
    normals = _front_normals(rest.vertices, count)
    weights = _front_weights(rest, count)
    profile = SurfaceLayerProfile(tissue.inflation_amount, tissue.minimum_amount, tissue.field_power)
    spec = SurfaceTissuePipelineSpec(inflation=profile,
        geometric=GeometricRelaxationSpec(tissue.sagginess, tuple(tissue.gravity), tissue.sag_limit))
    fake = SimpleNamespace(vertices=rest.vertices, base_vertex_count=count, thicknesses=_thicknesses(rest, count))
    solved = _surface_geometric_vertices(fake, normals, weights, spec.geometric)
    fixed = set(_fixed_indices(tissue, rest))
    return tuple(rest.vertices[index] if index in fixed else point for index, point in enumerate(solved))


def _static_shape(tissue, rest, anchors):
    settings = StaticPouchSettings(
        int(tissue.iterations), int(tissue.constraint_passes), gravity_step_from_sagginess(tissue.sagginess),
        float(tissue.shape_retention), float(tissue.volume_retention), tuple(tissue.gravity),
        float(tissue.sag_limit),
    )
    fixed = _fixed_indices(tissue, rest)
    tethers = tuple(_tether(item, rest) for item in anchors if item[0] == "SOFT")
    result = solve_static_tissue(rest.vertices, rest.faces, fixed, settings, tethers, tissue.tolerance)
    return FinalShape(result.vertices, result.iterations, result.max_displacement)


def _fixed_indices(tissue, rest):
    values = set()
    for attachment in tissue.attachments:
        if str(attachment.mode) == "FIXED":
            values.update(rest.groups.get(str(attachment.mask_attribute).upper(), ()))
    return tuple(sorted(values))


def _tether(item, rest):
    _mode, index, anchor, strength = item
    distance = (Vector(rest.vertices[index]) - Vector(anchor)).length
    return StaticTether(index, tuple(anchor), distance, float(strength))


def _captured_row(root, scene, tissue, rest, index, runtime, capture_fn):
    raw = capture_fn(root, scene, tissue.host_scp_id, Vector(rest.vertices[index]), runtime)
    if raw is None:
        raise ValueError("Could not capture a tissue attachment.")
    return {"index": int(index), "raw": raw}


def _resolved_attachment(root, scene, tissue, rest, attachment, runtime, point_fn, normal_fn):
    rows = _json_rows(attachment.bindings_json)
    return [_resolved_row(root, scene, tissue, rest, attachment, runtime, row, point_fn, normal_fn)
            for row in rows]


def _resolved_row(root, scene, tissue, rest, attachment, runtime, row, point_fn, normal_fn):
    index = int(row.get("index", -1))
    if not 0 <= index < len(rest.vertices):
        raise ValueError("Attachment vertex index no longer resolves.")
    point = point_fn(root, scene, tissue.host_scp_id, row.get("raw", ""), runtime)
    normal = normal_fn(root, scene, tissue.host_scp_id, row.get("raw", ""), runtime)
    if point is None or normal is None:
        raise ValueError("Attachment binding no longer resolves.")
    anchor = Vector(point) + Vector(normal) * float(attachment.normal_offset)
    return str(attachment.mode), index, tuple(anchor), float(attachment.strength)


def _attachment_runtime(scene):
    from ..vcp.attachment_backend import attachment_runtime
    return attachment_runtime(scene)


def _blob_runtime(tissue):
    center = Vector(tissue.base_object_ref.matrix_world.translation)
    return SimpleNamespace(
        iterations=tissue.iterations, sag_strength=tissue.sagginess * 10.0,
        stiffness=tissue.shape_retention, sag_limit=tissue.sag_limit,
        gravity_dir=Vector(tissue.gravity), control_point_world=center,
    )


def _curve_mesh(rest):
    ring = _ring_size_from_groups(rest)
    return SimpleNamespace(vertices=rest.vertices, faces=rest.faces, ring_size=ring)


def _ring_size_from_groups(rest):
    backing = tuple(rest.groups.get("BACKING", ()))
    return 0 if not backing else max(3, len(rest.vertices) // max(1, len(backing) // 2))


def _suspension_indices(weights):
    values = [index for index, weight in enumerate(weights) if 0.45 <= float(weight) <= 0.75]
    step = max(1, len(values) // 9)
    return tuple(values[::step][:9])


def _front_normals(vertices, count):
    values = []
    for index in range(count):
        delta = Vector(vertices[index]) - Vector(vertices[count + index])
        values.append(tuple(delta.normalized() if delta.length > 1.0e-12 else Vector((0.0, 0.0, 1.0))))
    return tuple(values)


def _front_weights(rest, count):
    thickness = _thicknesses(rest, count)
    maximum = max(thickness) if thickness else 1.0
    return tuple(value / maximum for value in thickness)


def _thicknesses(rest, count):
    return tuple((Vector(rest.vertices[index]) - Vector(rest.vertices[count + index])).length
                 for index in range(count))


def _surface_geometric_vertices(rest, normals, weights, spec):
    gravity = Vector(spec.gravity)
    gravity.normalize() if gravity.length > 1.0e-12 else None
    front = [_surface_relaxed_point(rest.vertices[i], normals[i], weights[i], rest, spec, gravity)
             for i in range(rest.base_vertex_count)]
    return tuple(front) + tuple(rest.vertices[rest.base_vertex_count:])


def _surface_relaxed_point(point, normal, weight, rest, spec, gravity):
    unit = Vector(normal).normalized()
    tangent = gravity - unit * gravity.dot(unit)
    tangent.normalize() if tangent.length > 1.0e-12 else None
    amount = spec.sag_fraction * max(rest.thicknesses) * float(weight)
    amount = min(amount, spec.sag_limit) if spec.sag_limit > 0.0 else amount
    return tuple(Vector(point) + tangent * amount)


def _json_rows(raw):
    try:
        value = json.loads(str(raw or "[]"))
    except Exception:
        value = []
    if isinstance(value, dict):
        value = value.get("bindings", [])
    return list(value) if isinstance(value, list) else []
