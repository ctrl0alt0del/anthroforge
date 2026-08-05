import numpy as np
from mathutils import Vector

from .ownership_capture import density_rules, ownership_sources

try:
    from ...core.topology.model import SymmetryPlane, TopologyCapture, TopologyGuide
    from ...core.topology.protocol import capture_hash
    from ...core.topology.settings import settings_from_payload
except ImportError:
    from core.topology.model import SymmetryPlane, TopologyCapture, TopologyGuide
    from core.topology.protocol import capture_hash
    from core.topology.settings import settings_from_payload


def capture_topology(root, scene, depsgraph):
    skin = _draft_skin(root, scene)
    vertices, triangles = _mesh_arrays(skin, depsgraph)
    return capture_topology_surface(root, scene, depsgraph, vertices, triangles)


def capture_topology_surface(root, scene, depsgraph, vertices, triangles):
    settings = _root_settings(root)
    plane = _resolved_plane(root, settings)
    guides, warnings = _guides(root, scene, depsgraph)
    rules = density_rules(root)
    sources = ownership_sources(root, scene, depsgraph)
    lower, upper = vertices.min(axis=0), vertices.max(axis=0)
    digest = capture_hash(root.name, vertices, triangles, guides, settings, plane, rules, sources)
    return TopologyCapture(root.name, vertices, triangles, guides, lower, upper,
                           digest, settings, plane, tuple(warnings), rules, sources)


def _draft_skin(root, scene):
    skin = next((obj for obj in scene.objects if obj.get("af_draft_skin")
                 and obj.get("af_root_name") == root.name), None)
    if skin is None or skin.type != "MESH":
        raise ValueError("Generate a draft skin for the current root first.")
    return skin


def _mesh_arrays(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return _read_mesh(evaluated, mesh)
    finally:
        evaluated.to_mesh_clear()


def _read_mesh(obj, mesh):
    mesh.calc_loop_triangles()
    coordinates = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.vertices.foreach_get("co", coordinates)
    mesh.loop_triangles.foreach_get("vertices", triangles)
    return _world_points(coordinates.reshape((-1, 3)), obj.matrix_world), triangles.reshape((-1, 3))


def _world_points(points, matrix):
    values = np.column_stack((points, np.ones(len(points))))
    return (values @ np.asarray(matrix, dtype=np.float64).T)[:, :3]


def _root_settings(root):
    value = root.af_topology_settings
    payload = {"target_quad_count": value.target_quad_count,
               "symmetry_mode": value.symmetry_mode,
               "custom_origin": tuple(value.custom_origin),
               "custom_normal": tuple(value.custom_normal),
               "refinement_strategy": value.refinement_strategy}
    return settings_from_payload(payload)


def _resolved_plane(root, settings):
    if settings.symmetry_mode == "NONE":
        return None
    local_origin, local_normal = _local_plane(settings)
    origin = root.matrix_world @ Vector(local_origin)
    matrix = root.matrix_world.to_3x3().inverted().transposed()
    normal = matrix @ Vector(local_normal)
    if normal.length < 1e-12:
        raise ValueError("Custom symmetry normal cannot be zero.")
    return SymmetryPlane(np.asarray(origin), np.asarray(normal.normalized()))


def _local_plane(settings):
    axes = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}
    if settings.symmetry_mode in axes:
        return (0.0, 0.0, 0.0), axes[settings.symmetry_mode]
    if settings.symmetry_mode != "CUSTOM":
        raise ValueError(f"Unsupported symmetry mode: {settings.symmetry_mode}")
    return settings.custom_origin, settings.custom_normal


def _guides(root, scene, depsgraph):
    modes = {str(item.id): str(item.topology_mode) for item in root.af_vcp_system.fibers}
    objects = [obj for obj in scene.objects if _is_loop_proxy(obj, root.name, modes)]
    records, warnings = [], []
    for obj in sorted(objects, key=_guide_sort_key):
        points = _curve_points(obj, depsgraph)
        if len(points) < 3:
            warnings.append(f"Closed topology guide {obj.name} has fewer than three points.")
            continue
        records.append(TopologyGuide(len(records), _fiber_id(obj), obj.name,
                                     _mirror_role(obj), points))
    return tuple(records), warnings


def _is_loop_proxy(obj, root_name, modes):
    fiber_id = _fiber_id(obj)
    return bool(obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name
                and modes.get(fiber_id) == "LOOP")


def _fiber_id(obj):
    return str(obj.get("af_source_fiber_id") or obj.get("af_fiber_id") or "")


def _mirror_role(obj):
    return "MIRROR" if obj.get("af_fiber_mirror_proxy") else "ORIGINAL"


def _guide_sort_key(obj):
    return (_fiber_id(obj), _mirror_role(obj), obj.name)


def _curve_points(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    splines = tuple(getattr(evaluated.data, "splines", ()))
    if not splines:
        return np.empty((0, 3), dtype=np.float64)
    points = tuple(getattr(splines[0], "points", ()))
    local = np.asarray([point.co[:3] for point in points], dtype=np.float64)
    return _world_points(local, evaluated.matrix_world)
