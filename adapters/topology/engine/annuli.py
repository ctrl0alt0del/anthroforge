import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from . import guides as guide_test


@dataclass(frozen=True)
class SurfaceLoop:
    name: str
    points: np.ndarray
    normals: np.ndarray
    perimeter: float
    center: np.ndarray
    symmetric: bool


@dataclass(frozen=True)
class AnnulusPatch:
    name: str
    source_names: tuple
    rings: np.ndarray
    normals: np.ndarray
    faces: np.ndarray


@dataclass(frozen=True)
class SymmetryPlane:
    origin: np.ndarray
    normal: np.ndarray


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--rows", type=int, default=5)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def surface_loops(guides, bvh, diagonal, graph, tree, vertices, symmetry):
    projected = [_surface_loop(guide, bvh, graph, tree, vertices, symmetry, diagonal) for guide in guides if guide.closed]
    valid = tuple(loop for loop in projected if loop is not None)
    return deduplicate_loops(valid, diagonal / 160.0)


def _surface_loop(guide, bvh, graph, tree, vertices, symmetry, diagonal):
    projected = guide_test.projected_guide(guide, bvh)
    if projected is None:
        return None
    points = geodesic_closure(projected[0], graph, tree, vertices, guide.name)
    points, normals = project_points(points, bvh)
    points, normals = resample_fields(points, normals, 192)
    points, normals = project_points(points, bvh)
    perimeter = loop_perimeter(points)
    symmetric = symmetry is not None and reflection_error(guide.points, symmetry) < diagonal / 40.0
    return SurfaceLoop(guide.name, points, normals, perimeter, points.mean(axis=0), symmetric)


def surface_graph(vertices, faces):
    from scipy.sparse import coo_matrix
    edges = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    edges = np.vstack((edges, edges[:, ::-1]))
    weights = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    return coo_matrix((weights, (edges[:, 0], edges[:, 1])), shape=(len(vertices),) * 2).tocsr()


def geodesic_closure(points, graph, tree, vertices, guide_name):
    if endpoint_gap_is_local(points):
        return points
    from scipy.sparse.csgraph import dijkstra
    start, finish = tree.query((points[-1], points[0]))[1]
    _distances, predecessors = dijkstra(graph, indices=start, return_predecessors=True)
    path = predecessor_path(int(start), int(finish), predecessors)
    indices = validated_path_indices(path, start, finish, len(vertices), guide_name)
    return np.vstack((points, vertices[indices])) if len(indices) else points


def validated_path_indices(path, start, finish, vertex_count, guide_name):
    if not path:
        return np.empty(0, dtype=np.intp)
    indices = np.asarray(path, dtype=np.intp)
    endpoints = indices[0] == start and indices[-1] == finish
    in_range = bool(np.all((indices >= 0) & (indices < vertex_count)))
    if not endpoints or not in_range:
        raise RuntimeError(f"Topology guide '{guide_name}' returned an invalid closure path.")
    return indices[1:-1]


def endpoint_gap_is_local(points):
    segments = np.linalg.norm(np.diff(points, axis=0), axis=1)
    typical = max(float(np.median(segments)), 1.0e-9)
    return float(np.linalg.norm(points[-1] - points[0])) <= 2.0 * typical


def predecessor_path(start, finish, predecessors):
    path, current = [finish], finish
    while current != start and current >= 0:
        current = int(predecessors[current])
        path.append(current)
    return tuple(reversed(path)) if current == start else ()


def project_points(points, bvh):
    projected = [guide_test._nearest(bvh, point) for point in points]
    locations = np.asarray([hit[0] for hit in projected])
    normals = normalize(np.asarray([hit[1] for hit in projected]))
    return locations, normals


def resample_fields(points, normals, count):
    closed_points = np.vstack((points, points[0]))
    closed_normals = np.vstack((normals, normals[0]))
    cumulative = loop_cumulative(closed_points)
    samples = np.linspace(0.0, cumulative[-1], count, endpoint=False)
    new_points = interpolate_rows(samples, cumulative, closed_points)
    new_normals = interpolate_rows(samples, cumulative, closed_normals)
    return new_points, normalize(new_normals)


def loop_cumulative(points):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return np.concatenate(([0.0], np.cumsum(lengths)))


def interpolate_rows(samples, cumulative, values):
    return np.column_stack([np.interp(samples, cumulative, values[:, axis]) for axis in range(3)])


def normalize(values):
    lengths = np.linalg.norm(values, axis=1)
    lengths[lengths < 1.0e-12] = 1.0
    return values / lengths[:, None]


def loop_perimeter(points):
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def deduplicate_loops(loops, tolerance):
    result = []
    for loop in loops:
        if not any(loop_distance(loop, other) < tolerance for other in result):
            result.append(loop)
    return tuple(result)


def loop_distance(first, second):
    from scipy.spatial import cKDTree
    first_to_second = cKDTree(second.points).query(first.points, workers=-1)[0]
    second_to_first = cKDTree(first.points).query(second.points, workers=-1)[0]
    return float(max(first_to_second.max(), second_to_first.max()))


def pair_nested_loops(loops):
    remaining, pairs = list(loops), []
    while len(remaining) > 1:
        first = remaining.pop(0)
        index = nearest_loop_index(first, remaining)
        second = remaining.pop(index)
        pairs.append(tuple(sorted((first, second), key=lambda loop: -loop.perimeter)))
    return tuple(pairs)


def nearest_loop_index(loop, candidates):
    scores = [pair_score(loop, candidate) for candidate in candidates]
    return int(np.argmin(scores))


def pair_score(first, second):
    center_distance = np.linalg.norm(first.center - second.center)
    size = max(min(first.perimeter, second.perimeter), 1.0e-6)
    return float(center_distance / size)


def build_patches(pairs, bvh, diagonal, rows, symmetry):
    patches = tuple(build_patch_options(pair, bvh, diagonal, rows, index, symmetry) for index, pair in enumerate(pairs))
    return preserve_mirrored_patches(patches, symmetry, diagonal)


def preserve_mirrored_patches(patches, plane, diagonal):
    if plane is None:
        return tuple(patches)
    result, used = list(patches), set()
    candidates = sorted((patch_pair_error(first, second, plane), i, j)
                        for i, first in enumerate(patches) for j, second in enumerate(patches[i + 1 :], i + 1))
    for error, first, second in candidates:
        if error >= diagonal / 40.0 or first in used or second in used:
            continue
        source, target = ordered_patch_sides(result, first, second, plane)
        result[target] = mirror_patch(result[source], result[target], plane)
        used.update((first, second))
    return tuple(result)


def patch_pair_error(first, second, plane):
    from scipy.spatial import cKDTree
    reflected = reflect_points(first.rings.reshape((-1, 3)), plane)
    target = second.rings.reshape((-1, 3))
    return float(np.quantile(cKDTree(target).query(reflected, workers=-1)[0], 0.95))


def ordered_patch_sides(patches, first, second, plane):
    signed = [np.dot(patches[index].rings.mean(axis=(0, 1)) - plane.origin, plane.normal) for index in (first, second)]
    return (first, second) if signed[0] >= signed[1] else (second, first)


def mirror_patch(source, target, plane):
    rings = reflect_points(source.rings.reshape((-1, 3)), plane).reshape(source.rings.shape)
    normals = reflect_vectors(source.normals.reshape((-1, 3)), plane).reshape(source.normals.shape)
    return AnnulusPatch(target.name, target.source_names, rings, normals, source.faces[:, ::-1])


def reflect_vectors(vectors, plane):
    distances = vectors @ plane.normal
    return vectors - (2.0 * distances[:, None] * plane.normal)


def build_patch_options(pair, bvh, diagonal, rows, index, symmetry):
    direct = build_patch(pair, bvh, diagonal, rows, index)
    if patch_inversions(direct, bvh) == 0:
        return direct
    planar = build_planar_pair_patch(pair, bvh, diagonal, rows, index, symmetry)
    if patch_inversions(planar, bvh) == 0:
        return planar
    radial = build_radial_patch(pair[0], bvh, diagonal, rows, index)
    return min((direct, planar, radial), key=lambda patch: patch_inversions(patch, bvh))


def patch_inversions(patch, bvh):
    return inverted_faces(patch.rings.reshape((-1, 3)), patch.faces, bvh)


def build_planar_pair_patch(pair, bvh, diagonal, rows, index, symmetry):
    segments = segment_count(pair, diagonal)
    outer = resample_fields(pair[0].points, pair[0].normals, segments)
    inner = align_loop(outer, resample_fields(pair[1].points, pair[1].normals, segments))
    plane = symmetry if symmetry_candidate(pair, symmetry, diagonal) else None
    center, basis, normal, fields = planar_pair_fields(outer, inner, plane)
    rings, normals = projected_planar_rings(center, basis, normal, fields, rows, bvh, diagonal)
    rings, normals = preserve_symmetry(rings, normals, pair, symmetry, bvh, diagonal)
    faces = orient_faces(rings.reshape((-1, 3)), annulus_faces(rows, segments), bvh)
    name = f"AF_TOPO_ANNULUS_{index + 1:02d}"
    return AnnulusPatch(name, (pair[0].name, pair[1].name), rings, normals, faces)


def planar_pair_fields(outer, inner, symmetry):
    combined = np.vstack((outer[0], inner[0]))
    center, basis, normal = planar_frame(combined, symmetry)
    normal *= np.sign(np.dot(normal, np.vstack((outer[1], inner[1])).mean(axis=0)))
    planar = tuple((loop[0] - center) @ basis.T for loop in (outer, inner))
    fields = nested_polar_fields(planar, len(outer[0]))
    return center, basis, normal, fields


def planar_frame(points, symmetry):
    center = points.mean(axis=0)
    _u, _singular, frame = np.linalg.svd(points - center, full_matrices=False)
    if symmetry is None:
        return center, frame[:2], np.cross(frame[0], frame[1])
    center -= np.dot(center - symmetry.origin, symmetry.normal) * symmetry.normal
    normal = frame[2] - (np.dot(frame[2], symmetry.normal) * symmetry.normal)
    normal /= max(float(np.linalg.norm(normal)), 1.0e-12)
    second = np.cross(normal, symmetry.normal)
    return center, np.asarray((symmetry.normal, second)), normal


def nested_polar_fields(planar, count):
    angles = np.linspace(-math.pi, math.pi, count, endpoint=False)
    radii = tuple(fourier_smooth(polar_radii(field, angles)[:, None], 8)[:, 0] for field in planar)
    outer, inner = np.maximum(radii[0], radii[1]), np.minimum(radii[0], radii[1])
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    return outer[:, None] * directions, inner[:, None] * directions


def polar_radii(planar, targets):
    angles = np.arctan2(planar[:, 1], planar[:, 0])
    radii = np.linalg.norm(planar, axis=1)
    order = np.argsort(angles)
    angles, radii = angles[order], radii[order]
    wrapped_angles = np.concatenate((angles[-1:] - 2.0 * math.pi, angles, angles[:1] + 2.0 * math.pi))
    wrapped_radii = np.concatenate((radii[-1:], radii, radii[:1]))
    return np.interp(targets, wrapped_angles, wrapped_radii)


def preserve_symmetry(rings, normals, pair, plane, bvh, diagonal):
    if not symmetry_candidate(pair, plane, diagonal):
        return rings, normals
    symmetric = np.asarray([symmetrize_ring(ring, plane, diagonal / 10000.0) for ring in rings])
    hits = [[guide_test._nearest(bvh, point) for point in ring] for ring in symmetric]
    hit_normals = np.asarray([[hit[1] for hit in row] for row in hits])
    return symmetric, normalize(hit_normals.reshape((-1, 3))).reshape(hit_normals.shape)


def symmetry_candidate(pair, plane, diagonal):
    if plane is None:
        return False
    crosses = [crosses_plane(loop.points, plane) for loop in pair]
    return all(crosses) and all(loop.symmetric for loop in pair)


def reflection_error(points, plane):
    return float(np.quantile(reflection_distances(points, plane), 0.95))


def reflection_distances(points, plane):
    from scipy.spatial import cKDTree
    return cKDTree(points).query(reflect_points(points, plane), workers=-1)[0]


def crosses_plane(points, plane):
    signed = (points - plane.origin) @ plane.normal
    return float(signed.min()) < 0.0 < float(signed.max())


def symmetrize_ring(points, plane, tolerance):
    from scipy.optimize import linear_sum_assignment
    signed = (points - plane.origin) @ plane.normal
    center, positive, negative = np.abs(signed) <= tolerance, signed > tolerance, signed < -tolerance
    if np.count_nonzero(positive) != np.count_nonzero(negative):
        return points
    cost = pair_distances(reflect_points(points[positive], plane), points[negative])
    rows, columns = linear_sum_assignment(cost)
    result = assign_symmetric_pairs(points, positive, negative, rows, columns, plane)
    result[center] -= signed[center, None] * plane.normal
    return result


def pair_distances(first, second):
    return np.linalg.norm(first[:, None, :] - second[None, :, :], axis=2)


def assign_symmetric_pairs(points, positive, negative, rows, columns, plane):
    result = points.copy()
    positive_ids, negative_ids = np.flatnonzero(positive)[rows], np.flatnonzero(negative)[columns]
    averaged = 0.5 * (points[positive_ids] + reflect_points(points[negative_ids], plane))
    result[positive_ids] = averaged
    result[negative_ids] = reflect_points(averaged, plane)
    return result


def reflect_points(points, plane):
    distances = (points - plane.origin) @ plane.normal
    return points - (2.0 * distances[:, None] * plane.normal)


def projected_planar_rings(center, basis, normal, fields, rows, bvh, diagonal):
    rings, normals = [], []
    for factor in np.linspace(0.0, 1.0, rows):
        planar = ((1.0 - factor) * fields[0]) + (factor * fields[1])
        points, surface_normals = ray_project_points(center + (planar @ basis), normal, bvh, diagonal)
        rings.append(points)
        normals.append(surface_normals)
    return np.asarray(rings), np.asarray(normals)


def ray_project_points(points, normal, bvh, diagonal):
    hits = [ray_project_point(point, normal, bvh, diagonal) for point in points]
    locations = np.asarray([hit[0] for hit in hits])
    normals = normalize(np.asarray([hit[1] for hit in hits]))
    return locations, normals


def ray_project_point(point, normal, bvh, diagonal):
    origin = Vector(point + (normal * diagonal))
    hit = bvh.ray_cast(origin, Vector(-normal), diagonal * 2.0)
    return (hit[0], hit[1]) if hit[0] is not None else guide_test._nearest(bvh, point)


def build_radial_patch(loop, bvh, diagonal, rows, index):
    candidates = []
    for divisor in (90.0, 120.0, 160.0, 220.0, 320.0):
        candidate = radial_patch_candidate(loop, bvh, diagonal, diagonal / divisor, rows, index)
        candidates.append(candidate)
        if patch_inversions(candidate, bvh) == 0:
            return candidate
    return min(candidates, key=lambda patch: patch_inversions(patch, bvh))


def radial_patch_candidate(loop, bvh, diagonal, half_width, rows, index):
    segments = segment_count((loop,), diagonal)
    points, normals = resample_fields(loop.points, loop.normals, segments)
    points, basis, planar = planar_periodic_loop(points, bvh)
    distances = np.linspace(-half_width, half_width, rows)
    rings, ring_normals = radial_surface_rings(points, basis, planar, distances, bvh)
    faces = orient_faces(rings.reshape((-1, 3)), annulus_faces(rows, segments), bvh)
    return AnnulusPatch(f"AF_TOPO_ANNULUS_{index + 1:02d}", (loop.name,), rings, ring_normals, faces)


def planar_periodic_loop(points, bvh):
    center = points.mean(axis=0)
    _u, _singular, basis = np.linalg.svd(points - center, full_matrices=False)
    planar = fourier_smooth((points - center) @ basis[:2].T, 6)
    seeds = center + (planar @ basis[:2])
    projected = [guide_test._nearest(bvh, point) for point in seeds]
    locations = np.asarray([hit[0] for hit in projected])
    return locations, basis[:2], planar


def fourier_smooth(values, harmonics):
    spectrum = np.fft.rfft(values, axis=0)
    spectrum[harmonics + 1 :] = 0.0
    return np.fft.irfft(spectrum, n=len(values), axis=0)


def radial_surface_rings(points, basis, planar, distances, bvh):
    rings, normals = [], []
    radial = planar / np.maximum(np.linalg.norm(planar, axis=1)[:, None], 1.0e-9)
    directions = radial @ basis
    for distance in distances:
        projected = [guide_test._nearest(bvh, point) for point in points + (directions * distance)]
        rings.append(np.asarray([hit[0] for hit in projected]))
        normals.append(normalize(np.asarray([hit[1] for hit in projected])))
    return np.asarray(rings), np.asarray(normals)


def build_patch(pair, bvh, diagonal, rows, index):
    segments = segment_count(pair, diagonal)
    outer = resample_fields(pair[0].points, pair[0].normals, segments)
    inner = resample_fields(pair[1].points, pair[1].normals, segments)
    inner = align_loop(outer, inner)
    rings, normals = interpolate_surface_rings(outer, inner, bvh, rows)
    faces = annulus_faces(rows, segments)
    faces = orient_faces(rings.reshape((-1, 3)), faces, bvh)
    return AnnulusPatch(f"AF_TOPO_ANNULUS_{index + 1:02d}", (pair[0].name, pair[1].name), rings, normals, faces)


def segment_count(pair, diagonal):
    target = max(diagonal / 80.0, 1.0e-6)
    raw = int(math.ceil(max(loop.perimeter for loop in pair) / target))
    rounded = int(math.ceil(raw / 4.0) * 4)
    return min(96, max(24, rounded))


def align_loop(reference, candidate):
    best = None
    for points, normals in orientation_options(candidate):
        for shift in range(len(points)):
            score = np.square(reference[0] - np.roll(points, shift, axis=0)).sum()
            if best is None or score < best[0]:
                best = score, np.roll(points, shift, axis=0), np.roll(normals, shift, axis=0)
    return best[1], best[2]


def orientation_options(loop):
    points, normals = loop
    return ((points, normals), (points[::-1], normals[::-1]))


def interpolate_surface_rings(outer, inner, bvh, rows):
    rings, normals = [], []
    for factor in np.linspace(0.0, 1.0, rows):
        seeds = ((1.0 - factor) * outer[0]) + (factor * inner[0])
        projected = [guide_test._nearest(bvh, point) for point in seeds]
        rings.append(np.asarray([hit[0] for hit in projected]))
        normals.append(normalize(np.asarray([hit[1] for hit in projected])))
    return np.asarray(rings), np.asarray(normals)


def annulus_faces(rows, segments):
    faces = []
    for row in range(rows - 1):
        for column in range(segments):
            next_column = (column + 1) % segments
            faces.append(quad_indices(row, column, next_column, segments))
    return np.asarray(faces, dtype=np.int32)


def quad_indices(row, column, next_column, segments):
    first = row * segments
    second = (row + 1) * segments
    return first + column, first + next_column, second + next_column, second + column


def orient_faces(vertices, faces, bvh):
    centers = vertices[faces].mean(axis=1)
    face_normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 3]] - vertices[faces[:, 0]])
    surface_normals = np.asarray([guide_test._nearest(bvh, center)[1] for center in centers])
    if float(np.mean(np.einsum("ij,ij->i", face_normals, surface_normals))) < 0.0:
        return faces[:, ::-1]
    return faces


def create_patch_objects(patches, collection, value):
    objects = []
    for patch in patches:
        objects.append(create_patch_object(patch, collection, value))
    return tuple(objects)


def create_patch_object(patch, collection, value):
    mesh = bpy.data.meshes.new(f"{patch.name}_MESH")
    mesh.from_pydata(patch.rings.reshape((-1, 3)).tolist(), [], patch.faces.tolist())
    obj = bpy.data.objects.new(patch.name, mesh)
    collection.objects.link(obj)
    if value is not None:
        obj.data.materials.append(value)
    add_ring_attribute(obj, patch)
    obj["af_topology_sources"] = json.dumps(patch.source_names)
    return obj


def add_ring_attribute(obj, patch):
    attribute = obj.data.attributes.new("af_topology_ring", "INT", "POINT")
    segments = patch.rings.shape[1]
    attribute.data.foreach_set("value", np.repeat(np.arange(len(patch.rings)), segments))


def make_wire_objects(objects, collection, value):
    return tuple(make_wire_object(obj, collection, value) for obj in objects)


def make_wire_object(obj, collection, value):
    wire = obj.copy()
    wire.data = obj.data.copy()
    wire.name = f"{obj.name}_WIRE"
    collection.objects.link(wire)
    wire.data.materials.clear()
    wire.data.materials.append(value)
    modifier = wire.modifiers.new("AF_TOPO_WIREFRAME", "WIREFRAME")
    modifier.thickness, modifier.use_replace = 0.003, True
    return wire


def ring_lines(patches, rows, offset):
    lines = []
    for patch in patches:
        for row in rows:
            points = patch.rings[row] + (patch.normals[row] * offset)
            lines.append((points, True))
    return lines


def requested_lines(loops, offset):
    return [(loop.points + (loop.normals * offset), True) for loop in loops]


def visual_materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_ANNULUS_SKIN", (0.16, 0.20, 0.26)))
    return {
        "patch": guide_test.material("AF_ANNULUS_PATCH", (0.035, 0.09, 0.12)),
        "wire": guide_test.material("AF_ANNULUS_WIRE", (0.03, 0.78, 1.0), 1.6),
        "requested": guide_test.material("AF_ANNULUS_REQUESTED", (1.0, 0.48, 0.03), 1.5),
        "boundary": guide_test.material("AF_ANNULUS_BOUNDARY", (1.0, 0.03, 0.025), 2.0),
        "middle": guide_test.material("AF_ANNULUS_MIDDLE", (0.15, 1.0, 0.28), 1.8),
    }


def create_visuals(skin, loops, patches, collection, diagonal):
    values = visual_materials(skin)
    patch_objects = create_patch_objects(patches, collection, values["patch"])
    wire_objects = make_wire_objects(patch_objects, collection, values["wire"])
    scale = diagonal * 0.002
    requested = guide_test.curve_object("AF_ANNULUS_REQUESTED", requested_lines(loops, scale * 2.0), collection, values["requested"], scale)
    boundary = guide_test.curve_object("AF_ANNULUS_BOUNDARIES", ring_lines(patches, (0, -1), scale * 2.3), collection, values["boundary"], scale * 1.25)
    middle = guide_test.curve_object("AF_ANNULUS_ROWS", ring_lines(patches, range(1, len(patches[0].rings) - 1), scale * 2.1), collection, values["middle"], scale * 0.75)
    return skin, patch_objects, wire_objects, requested, boundary, middle


def prepare_render(objects):
    for obj in tuple(bpy.context.scene.objects):
        obj.hide_render = True
    guide_test._render_settings()
    camera = guide_test._camera()
    guide_test._lights()
    return camera, objects


def render_variants(objects):
    skin, patches, wires, requested, boundary, middle = objects
    return {
        "requested_guides": {skin, requested},
        "quad_annuli": {*patches, *wires, boundary, middle},
        "skin_overlay": {skin, *wires, boundary, middle},
        "loop_rows": {skin, boundary, middle},
    }


def set_visibility(objects, visible):
    skin, patches, wires, requested, boundary, middle = objects
    for obj in (skin, *patches, *wires, requested, boundary, middle):
        obj.hide_render = obj not in visible


def render_all(camera, objects, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    variants = render_variants(objects)
    for name, visible in variants.items():
        set_visibility(objects, visible)
        guide_test._render_view(camera, (0.0, -8.0, 1.25), folder / f"{name}_front.png")
    render_threequarter(camera, objects, variants, folder)
    contact_sheet(folder, tuple(variants))


def render_threequarter(camera, objects, variants, folder):
    set_visibility(objects, variants["skin_overlay"])
    guide_test._render_view(camera, (4.6, -7.0, 2.8), folder / "skin_overlay_threequarter.png")


def contact_sheet(folder, names):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{name}_front.png").convert("RGB") for name in names]
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    labels = ("Authored closed guides", "Constructed quad annuli", "Annuli on draft skin", "Verified topology rows")
    for index, (image, label) in enumerate(zip(images, labels)):
        paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_annuli_comparison.png")


def paste_panel(canvas, image, label, index, image_draw):
    x, y = (index % 2) * 720, (index // 2) * 720
    canvas.paste(image, (x, y))
    draw = image_draw.Draw(canvas)
    draw.rectangle((x, y, x + 390, y + 38), fill=(5, 8, 14))
    draw.text((x + 12, y + 10), label, fill=(235, 240, 248))


def patch_metrics(patch, bvh, symmetry):
    vertices = patch.rings.reshape((-1, 3))
    ratios = face_aspect_ratios(vertices, patch.faces)
    errors = [_surface_error(point, bvh) for point in vertices]
    symmetry_errors = reflection_distances(vertices, symmetry)
    return {
        "name": patch.name, "sources": patch.source_names,
        "segments": patch.rings.shape[1], "rows": patch.rings.shape[0],
        "quads": len(patch.faces), "aspect_p95": float(np.quantile(ratios, 0.95)),
        "projection_error_max": max(errors), "inverted_faces": inverted_faces(vertices, patch.faces, bvh),
        "reflection_error_max": float(symmetry_errors.max()),
    }


def face_aspect_ratios(vertices, faces):
    edges = np.stack([vertices[np.roll(faces, -shift, axis=1)] - vertices[faces] for shift in (1,)], axis=0)[0]
    lengths = np.linalg.norm(edges, axis=2)
    return lengths.max(axis=1) / np.maximum(lengths.min(axis=1), 1.0e-9)


def _surface_error(point, bvh):
    hit = guide_test._nearest(bvh, point)
    return float(np.linalg.norm(np.asarray(hit[0]) - point)) if hit else math.inf


def inverted_faces(vertices, faces, bvh):
    centers = vertices[faces].mean(axis=1)
    normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 3]] - vertices[faces[:, 0]])
    surface = np.asarray([guide_test._nearest(bvh, center)[1] for center in centers])
    return int(np.count_nonzero(np.einsum("ij,ij->i", normals, surface) <= 0.0))


def metrics_payload(loops, pairs, patches, bvh, symmetry):
    combined = np.vstack([patch.rings.reshape((-1, 3)) for patch in patches])
    return {
        "unique_closed_guides": len(loops), "paired_annuli": len(pairs),
        "all_quads": True, "edge_loop_rows": sum(len(patch.rings) for patch in patches),
        "guide_symmetry": {loop.name: loop.symmetric for loop in loops},
        "combined_reflection_error_max": float(reflection_distances(combined, symmetry).max()),
        "patches": [patch_metrics(patch, bvh, symmetry) for patch in patches],
    }


def save_outputs(path, metrics, patch_objects):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    for obj in patch_objects:
        obj["af_topology_annulus_test"] = True
        obj["af_topology_annulus_stats"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True)


def root_symmetry_plane(root):
    origin = np.asarray(root.matrix_world.translation, dtype=np.float64)
    normal = np.asarray(root.matrix_world.to_3x3() @ Vector((1.0, 0.0, 0.0)), dtype=np.float64)
    normal /= max(float(np.linalg.norm(normal)), 1.0e-12)
    return SymmetryPlane(origin, normal)


def build_prototype(args):
    guide_test.ensure_runtime()
    from scipy.spatial import cKDTree
    root, skin = guide_test.scene_inputs()
    guides = guide_test.collect_guides(root)
    vertices, faces, _normals = guide_test.mesh_arrays(skin)
    bvh = guide_test.surface_bvh(vertices, faces)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    graph, tree = surface_graph(vertices, faces), cKDTree(vertices)
    symmetry = root_symmetry_plane(root)
    loops = surface_loops(guides, bvh, diagonal, graph, tree, vertices, symmetry)
    pairs = pair_nested_loops(loops)
    patches = build_patches(pairs, bvh, diagonal, args.rows, symmetry)
    collection = guide_test.make_collection("AF_TOPOLOGY_ANNULUS_TEST")
    return skin, loops, pairs, patches, bvh, diagonal, collection, symmetry


def finish_prototype(args, data):
    skin, loops, pairs, patches, bvh, diagonal, collection, symmetry = data
    metrics = metrics_payload(loops, pairs, patches, bvh, symmetry)
    objects = create_visuals(skin, loops, patches, collection, diagonal)
    camera, objects = prepare_render(objects)
    render_all(camera, objects, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    save_outputs(args.output, metrics, objects[1])
    print("AF_TOPOLOGY_ANNULUS_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
