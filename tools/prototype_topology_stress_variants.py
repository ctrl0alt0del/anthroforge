from pathlib import Path
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_cube_shell as cube_test
import prototype_topology_field as field_test
import prototype_topology_guides as guide_test


def apply_variant(name):
    values = {"no_guides": no_guides, "mouth_only": mouth_only,
              "eyes_only": eyes_only, "alien_forehead": alien_forehead,
              "moved_mismatched": moved_mismatched}
    if name not in values:
        raise RuntimeError(f"Unknown topology stress variant: {name}")
    values[name]()


def anchors():
    return list(field_test.anchor_objects())


def mouth_and_eyes():
    values = anchors()
    mouth = min(values, key=lambda obj: world_points(obj)[:, 2].mean())
    return mouth, [obj for obj in values if obj != mouth]


def set_enabled(predicate):
    for obj in anchors():
        obj["af_topology_annulus_test"] = bool(predicate(obj))


def no_guides():
    set_enabled(lambda _obj: False)


def mouth_only():
    mouth, _eyes = mouth_and_eyes()
    set_enabled(lambda obj: obj == mouth)


def eyes_only():
    mouth, _eyes = mouth_and_eyes()
    set_enabled(lambda obj: obj != mouth)


def alien_forehead():
    mouth, _eyes = mouth_and_eyes()
    clone = duplicate_anchor(mouth, "AF_TOPO_ANNULUS_04_FOREHEAD")
    points = forehead_annulus(5, 40)
    mapping = cube_test.reflection_index_map(points)
    projected = front_project_points(points)
    install_mesh(clone, projected, annulus_faces(5, 40), 5, 40)
    enforce_mapping(clone, mapping)


def forehead_annulus(rows, count):
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    values = []
    for row in range(rows):
        factor = row / max(rows - 1, 1)
        radius_x, radius_z = 0.20 + (0.16 * factor), 0.11 + (0.10 * factor)
        ring = np.column_stack((radius_x * np.cos(angles),
                                np.zeros(count), radius_z * np.sin(angles)))
        values.append(ring + (0.0, -0.79, 1.86))
    return np.vstack(values)


def duplicate_anchor(source, name):
    clone = source.copy()
    clone.data = source.data.copy()
    clone.name = name
    clone.data.name = f"{name}_MESH"
    source.users_collection[0].objects.link(clone)
    clone["af_topology_annulus_test"] = True
    return clone


def moved_mismatched():
    mouth, eyes = mouth_and_eyes()
    replace_annulus(mouth, 36, True)
    mapping = cube_test.reflection_index_map(world_points(mouth))
    transform_anchor(mouth, (1.10, 1.0, 0.90), (0.0, 0.0, 0.04))
    enforce_mapping(mouth, mapping)
    for eye in eyes:
        replace_annulus(eye, 32)
        sign = np.sign(world_points(eye)[:, 0].mean())
        transform_anchor(eye, (1.12, 1.0, 1.08), (0.03 * sign, 0.0, 0.05))
    enforce_eye_symmetry(eyes)


def replace_annulus(obj, count, symmetric=False):
    rings = ordered_rings(obj)
    sampler = symmetric_loop if symmetric else cube_test.loop_samples
    sampled = [sampler(points, count) for points in rings]
    vertices = np.vstack(sampled)
    faces = annulus_faces(len(rings), count)
    install_mesh(obj, vertices, faces, len(rings), count)


def symmetric_loop(points, count):
    indices = cube_test.negative_half_indices(points)
    negative = sample_open(points[indices], (count // 2) + 1)
    positive = negative[-2:0:-1].copy()
    positive[:, 0] *= -1.0
    return np.vstack((negative, positive))


def sample_open(points, count):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    targets = np.linspace(0.0, cumulative[-1], count)
    indices = np.minimum(np.searchsorted(cumulative, targets, side="right") - 1,
                         len(points) - 2)
    indices[0] = 0
    factors = (targets - cumulative[indices]) / np.maximum(lengths[indices], 1.0e-12)
    return points[indices] + (factors[:, None] * (points[indices + 1] - points[indices]))


def ordered_rings(obj):
    points = world_points(obj)
    attribute = obj.data.attributes["af_topology_ring"]
    values = np.asarray([item.value for item in attribute.data], dtype=np.int32)
    return [points[values == ring] for ring in sorted(set(values.tolist()))]


def annulus_faces(rows, count):
    values = []
    for row in range(rows - 1):
        for index in range(count):
            nxt = (index + 1) % count
            values.append((row * count + index, row * count + nxt,
                           (row + 1) * count + nxt, (row + 1) * count + index))
    return values


def install_mesh(obj, vertices, faces, rows, count):
    mesh = bpy.data.meshes.new(f"{obj.name}_STRESS_MESH")
    mesh.from_pydata(vertices.tolist(), [], faces)
    attribute = mesh.attributes.new("af_topology_ring", "INT", "POINT")
    attribute.data.foreach_set("value", np.repeat(np.arange(rows), count))
    obj.data = mesh
    obj.matrix_world = Matrix.Identity(4)


def transform_anchor(obj, scale, translation):
    points = world_points(obj)
    center = points.mean(axis=0)
    transformed = center + ((points - center) * np.asarray(scale))
    set_world_points(obj, project_points(transformed + np.asarray(translation)))


def project_points(points):
    _root, skin = guide_test.scene_inputs()
    vertices, faces, _normals = guide_test.mesh_arrays(skin)
    bvh = guide_test.surface_bvh(vertices, faces)
    return np.asarray([guide_test._nearest(bvh, point)[0] for point in points])


def front_project_points(points):
    _root, skin = guide_test.scene_inputs()
    vertices, faces, _normals = guide_test.mesh_arrays(skin)
    bvh = guide_test.surface_bvh(vertices, faces)
    values = []
    for point in points:
        hit = bvh.ray_cast(Vector((point[0], -3.0, point[2])), Vector((0.0, 1.0, 0.0)))
        if hit[0] is None:
            raise RuntimeError("Forehead stress guide missed the draft skin.")
        values.append(tuple(hit[0]))
    return np.asarray(values)


def enforce_eye_symmetry(eyes):
    negative = min(eyes, key=lambda obj: world_points(obj)[:, 0].mean())
    positive = max(eyes, key=lambda obj: world_points(obj)[:, 0].mean())
    source = world_points(negative)
    reflected = source.copy()
    reflected[:, 0] *= -1.0
    mapping = nearest_mapping(world_points(positive), reflected)
    target = world_points(positive)
    target[mapping] = reflected
    set_world_points(positive, target)


def enforce_mapping(obj, mapping):
    points = world_points(obj)
    result = points.copy()
    for first, second in enumerate(mapping):
        if first > second:
            continue
        reflected = (-points[second, 0], points[second, 1], points[second, 2])
        average = 0.5 * (points[first] + reflected)
        result[first] = average
        result[second] = (-average[0], average[1], average[2])
    set_world_points(obj, result)


def nearest_mapping(points, queries):
    from scipy.spatial import cKDTree
    distances, indices = cKDTree(points).query(queries, workers=-1)
    if float(distances.max()) > 0.15:
        raise RuntimeError("Unable to pair moved stress-test eye guides.")
    return indices


def world_points(obj):
    return np.asarray([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])


def set_world_points(obj, points):
    inverse = obj.matrix_world.inverted()
    local = np.asarray([inverse @ Vector(point) for point in points], dtype=np.float64)
    obj.data.vertices.foreach_set("co", local.ravel())
    obj.data.update()
