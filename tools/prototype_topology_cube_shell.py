import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_field as field_test
import prototype_topology_global_layout as global_test
import prototype_topology_guides as guide_test


@dataclass(frozen=True)
class Transition:
    name: str
    vertices: np.ndarray
    faces: np.ndarray


@dataclass(frozen=True)
class HybridMesh:
    vertices: np.ndarray
    faces: np.ndarray


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--resolution", type=int, default=18)
    parser.add_argument("--target-faces", type=int, default=64000)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def cube_keys(resolution):
    values = []
    for first in range(resolution + 1):
        for second in range(resolution + 1):
            for third in range(resolution + 1):
                if any(value in {0, resolution} for value in (first, second, third)):
                    values.append((first, second, third))
    return tuple(values)


def cube_coordinates(keys, resolution):
    values = np.asarray(keys, dtype=np.float64)
    return (2.0 * values / float(resolution)) - 1.0


def face_key(axis, side, first, second):
    values = [0, 0, 0]
    values[axis] = side
    others = [index for index in range(3) if index != axis]
    values[others[0]], values[others[1]] = first, second
    return tuple(values)


def raw_face_keys(axis, side, first, second):
    return (face_key(axis, side, first, second),
            face_key(axis, side, first + 1, second),
            face_key(axis, side, first + 1, second + 1),
            face_key(axis, side, first, second + 1))


def oriented_face(keys, coordinates):
    points = coordinates[np.asarray(keys)]
    normal = np.cross(points[1] - points[0], points[2] - points[0])
    return keys if np.dot(normal, points.mean(axis=0)) > 0.0 else tuple(reversed(keys))


def cube_faces(keys, resolution):
    lookup = {key: index for index, key in enumerate(keys)}
    coordinates = cube_coordinates(keys, resolution)
    values = []
    for axis in range(3):
        for side in (0, resolution):
            values.extend(side_faces(axis, side, resolution, lookup, coordinates))
    return np.asarray(values, dtype=np.int32)


def side_faces(axis, side, resolution, lookup, coordinates):
    values = []
    for first in range(resolution):
        for second in range(resolution):
            raw = tuple(lookup[key] for key in raw_face_keys(axis, side, first, second))
            values.append(oriented_face(raw, coordinates))
    return values


def normalize_rows(values):
    lengths = np.maximum(np.linalg.norm(values, axis=1), 1.0e-12)
    return values / lengths[:, None]


def outside_hit(center, direction, inputs):
    distance = 1.5 * inputs.diagonal
    origin = center + (direction * distance)
    hit = inputs.bvh.ray_cast(Vector(origin), Vector(-direction), 3.0 * inputs.diagonal)
    if hit[0] is not None:
        return np.asarray(hit[0]), np.asarray(hit[1])
    nearest = guide_test._nearest(inputs.bvh, origin)
    return np.asarray(nearest[0]), np.asarray(nearest[1])


def project_cube(keys, resolution, inputs):
    vertices = initial_cage(keys, resolution, inputs)
    neighbors = vertex_neighbors(len(vertices), cube_faces(keys, resolution))
    normals = normalize_rows(vertices)
    for iteration in range(64):
        strength = 0.18 * max(0.0, 1.0 - (iteration / 52.0))
        vertices, normals = fit_cage_iteration(vertices, neighbors, inputs, strength)
        vertices, normals = symmetrize_projection(keys, resolution, vertices, normals)
    vertices, normals = final_surface_fit(vertices, normals, inputs)
    return symmetrize_projection(keys, resolution, vertices, normals)


def initial_cage(keys, resolution, inputs):
    directions = normalize_rows(cube_coordinates(keys, resolution))
    center = 0.5 * (inputs.vertices.min(axis=0) + inputs.vertices.max(axis=0))
    radius = 0.62 * inputs.diagonal
    return center + (directions * radius)


def vertex_neighbors(count, faces):
    values = [set() for _index in range(count)]
    for face in faces:
        for first, second in zip(face, np.roll(face, -1)):
            values[int(first)].add(int(second))
            values[int(second)].add(int(first))
    return tuple(np.asarray(sorted(value), dtype=np.int32) for value in values)


def nearest_surface(points, inputs):
    hits = [guide_test._nearest(inputs.bvh, point) for point in points]
    targets = np.asarray([hit[0] for hit in hits])
    normals = normalize_rows(np.asarray([hit[1] for hit in hits]))
    return targets, normals


def limited_displacement(delta, limit):
    lengths = np.maximum(np.linalg.norm(delta, axis=1), 1.0e-12)
    factors = np.minimum(0.42, limit / lengths)
    return delta * factors[:, None]


def neighbor_means(vertices, neighbors):
    return np.asarray([vertices[indices].mean(axis=0) for indices in neighbors])


def tangent_relaxation(vertices, neighbors, normals):
    values = neighbor_means(vertices, neighbors) - vertices
    normal_part = np.einsum("ij,ij->i", values, normals)[:, None] * normals
    return values - normal_part


def fit_cage_iteration(vertices, neighbors, inputs, strength):
    targets, normals = nearest_surface(vertices, inputs)
    inward = limited_displacement(targets - vertices, 0.035 * inputs.diagonal)
    tangent = tangent_relaxation(vertices, neighbors, normals)
    return vertices + inward + (strength * tangent), normals


def final_surface_fit(vertices, normals, inputs):
    targets, target_normals = nearest_surface(vertices, inputs)
    close = np.linalg.norm(targets - vertices, axis=1) < 0.06 * inputs.diagonal
    vertices[close] = targets[close]
    normals[close] = target_normals[close]
    return vertices, normalize_rows(normals)


def reflected(value):
    result = value.copy()
    result[0] *= -1.0
    return result


def symmetrize_projection(keys, resolution, vertices, normals):
    lookup = {key: index for index, key in enumerate(keys)}
    for index, key in enumerate(keys):
        partner = lookup[(resolution - key[0], key[1], key[2])]
        if index <= partner:
            symmetrize_pair(index, partner, vertices, normals)
    return vertices, normalize_rows(normals)


def symmetrize_pair(first, second, vertices, normals):
    vertex = 0.5 * (vertices[first] + reflected(vertices[second]))
    normal = 0.5 * (normals[first] + reflected(normals[second]))
    if first == second:
        vertex[0], normal[0] = 0.0, 0.0
    vertices[first], vertices[second] = vertex, reflected(vertex)
    normals[first], normals[second] = normal, reflected(normal)


def orient_projected_faces(vertices, normals, faces):
    values = []
    for face in faces:
        points = vertices[face]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        target = normals[face].mean(axis=0)
        values.append(face if np.dot(normal, target) >= 0.0 else face[::-1])
    return np.asarray(values, dtype=np.int32)


def create_mesh(vertices, faces, collection):
    mesh = bpy.data.meshes.new("AF_CUBE_SHELL_MESH")
    mesh.from_pydata(vertices.tolist(), [], faces.tolist())
    mesh.update()
    obj = bpy.data.objects.new("AF_CUBE_SHELL", mesh)
    collection.objects.link(obj)
    return obj


def create_hybrid_object(hybrid, collection):
    mesh = bpy.data.meshes.new("AF_CUBE_HYBRID_MESH")
    mesh.from_pydata(hybrid.vertices.tolist(), [], hybrid.faces.tolist())
    mesh.update()
    obj = bpy.data.objects.new("AF_CUBE_HYBRID", mesh)
    collection.objects.link(obj)
    return obj


def mesh_edges(faces):
    values = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)],
                        faces[:, (2, 3)], faces[:, (3, 0)]))
    return np.unique(np.sort(values, axis=1), axis=0)


def ring_frame(ring):
    center = ring.mean(axis=0)
    _values, vectors = np.linalg.eigh(np.cov((ring - center).T))
    return center, vectors[:, -1], vectors[:, -2], vectors[:, 0]


def local_points(points, center, first, second):
    relative = points - center
    return np.column_stack((relative @ first, relative @ second))


def anchor_face_mask(vertices, faces, ring, diagonal):
    center, first, second, normal = ring_frame(ring)
    polygon = local_points(ring, center, first, second) * 1.08
    centers = vertices[faces].mean(axis=1)
    local = local_points(centers, center, first, second)
    radius = np.linalg.norm(ring - center, axis=1).max()
    nearby = np.linalg.norm(centers - center, axis=1) < 1.8 * radius
    inside = np.asarray([global_test.point_in_polygon(point, polygon) for point in local])
    selected = keep_largest_mask_component(faces, nearby & inside)
    regular = regularize_cut(vertices, faces, selected, center)
    return fill_mask_holes(faces, regular)


def vertex_face_map(faces):
    values = {}
    for face_index, face in enumerate(faces):
        for vertex in face:
            values.setdefault(int(vertex), []).append(face_index)
    return values


def ambiguous_cut_vertices(faces, mask):
    edges = cut_boundary_edges(faces, mask)
    vertices, counts = np.unique(edges, return_counts=True)
    return vertices[counts > 2]


def fill_ambiguous_vertex(vertex, vertices, faces, mask, center, owners):
    candidates = [index for index in owners[int(vertex)] if not mask[index]]
    if not candidates:
        return False
    points = vertices[faces[np.asarray(candidates)]].mean(axis=1)
    mask[candidates[int(np.argmin(np.linalg.norm(points - center, axis=1)))]] = True
    return True


def regularize_cut(vertices, faces, mask, center):
    result, owners = mask.copy(), vertex_face_map(faces)
    for _iteration in range(12):
        ambiguous = ambiguous_cut_vertices(faces, result)
        if not len(ambiguous):
            break
        changed = sum(fill_ambiguous_vertex(value, vertices, faces, result, center, owners)
                      for value in ambiguous)
        if not changed:
            break
    return result


def face_neighbors(faces):
    values = [set() for _face in faces]
    for owners in edge_face_owners(faces).values():
        if len(owners) == 2:
            values[owners[0]].add(owners[1])
            values[owners[1]].add(owners[0])
    return values


def pop_face_component(pending, neighbors):
    values, stack = set(), [pending.pop()]
    while stack:
        face = stack.pop()
        values.add(face)
        linked = pending.intersection(neighbors[face])
        pending.difference_update(linked)
        stack.extend(linked)
    return values


def false_face_components(mask, neighbors):
    pending, values = set(np.flatnonzero(~mask).tolist()), []
    while pending:
        values.append(pop_face_component(pending, neighbors))
    return values


def true_face_components(mask, neighbors):
    pending, values = set(np.flatnonzero(mask).tolist()), []
    while pending:
        values.append(pop_face_component(pending, neighbors))
    return values


def keep_largest_mask_component(faces, mask):
    components = true_face_components(mask, face_neighbors(faces))
    result = np.zeros(len(mask), dtype=bool)
    if components:
        result[np.asarray(tuple(max(components, key=len)), dtype=np.int32)] = True
    return result


def recover_face_path(found, parents):
    values, current = [], int(found)
    while current != -1:
        values.append(current)
        current = parents[current]
    return values


def shortest_face_path(source, target, neighbors):
    from collections import deque
    queue = deque(source)
    parents = {int(value): -1 for value in source}
    while queue:
        current = queue.popleft()
        if current in target:
            return recover_face_path(current, parents)
        for linked in neighbors[current] - parents.keys():
            parents[linked] = current
            queue.append(linked)
    return ()


def connect_mask_components(faces, mask):
    neighbors = face_neighbors(faces)
    components = sorted(true_face_components(mask, neighbors), key=len, reverse=True)
    result = mask.copy()
    source = set(components[0]) if components else set()
    for target in components[1:]:
        path = shortest_face_path(source, target, neighbors)
        result[np.asarray(path, dtype=np.int32)] = True
        source.update(target | set(path))
    return result


def fill_mask_holes(faces, mask):
    result = mask.copy()
    components = false_face_components(result, face_neighbors(faces))
    for component in sorted(components, key=len)[:-1]:
        result[np.asarray(tuple(component), dtype=np.int32)] = True
    return result


def removed_faces(vertices, faces, anchors, diagonal):
    masks = [anchor_face_mask(vertices, faces, ordered_outer_ring(anchor), diagonal) for anchor in anchors]
    combined = symmetrize_face_mask(vertices, faces, np.logical_or.reduce(masks))
    return fill_mask_holes(faces, combined)


def symmetrize_face_mask(vertices, faces, mask):
    from scipy.spatial import cKDTree
    centers = vertices[faces].mean(axis=1)
    mirrored = centers.copy()
    mirrored[:, 0] *= -1.0
    distances, indices = cKDTree(centers).query(mirrored, workers=-1)
    if float(distances.max()) > 1.0e-5:
        raise RuntimeError("Cube face map is not bilaterally symmetric.")
    return mask | mask[indices]


def edge_face_owners(faces):
    owners = {}
    for face_index, face in enumerate(faces):
        for first, second in zip(face, np.roll(face, -1)):
            owners.setdefault(tuple(sorted((int(first), int(second)))), []).append(face_index)
    return owners


def cut_boundary_edges(faces, removed):
    owners = edge_face_owners(faces)
    values = [edge for edge, face_ids in owners.items() if len(face_ids) == 2 and removed[face_ids[0]] != removed[face_ids[1]]]
    return np.asarray(values, dtype=np.int32)


def boundary_adjacency(edges):
    values = {}
    for first, second in edges:
        values.setdefault(int(first), []).append(int(second))
        values.setdefault(int(second), []).append(int(first))
    return values


def ordered_boundary(start, adjacency):
    order, previous, current = [], -1, int(start)
    for _step in range(len(adjacency) + 1):
        if current in order:
            break
        order.append(current)
        options = [value for value in adjacency[current] if value != previous]
        previous, current = current, options[0] if options else -1
    return tuple(order), current == start


def boundary_loops(edges):
    adjacency, pending, values = boundary_adjacency(edges), set(np.unique(edges)), []
    while pending:
        order, closed = ordered_boundary(min(pending), adjacency)
        pending.difference_update(order)
        if closed and len(order) > 2:
            values.append(order)
    return tuple(values)


def object_boundary_edges(obj):
    faces = [tuple(polygon.vertices) for polygon in obj.data.polygons]
    owners = edge_face_owners(faces)
    return np.asarray([edge for edge, values in owners.items() if len(values) == 1], dtype=np.int32)


def ordered_anchor_rings(anchor):
    vertices = field_test.object_world_vertices(anchor)
    loops = boundary_loops(object_boundary_edges(anchor))
    return tuple(vertices[np.asarray(loop)] for loop in loops)


def ordered_outer_ring(anchor):
    rings = ordered_anchor_rings(anchor)
    return max(rings, key=global_test.ring_perimeter)


def kept_edges(faces, removed):
    return mesh_edges(faces[~removed])


def projected_edge_line(edge, vertices, normals):
    values = np.linspace(0.0, 1.0, 7)
    endpoints = vertices[edge] + (normals[edge] * 0.011)
    return endpoints[0][None, :] + (values[:, None] * (endpoints[1] - endpoints[0])[None, :])


def edge_lines(vertices, normals, faces):
    return tuple((projected_edge_line(edge, vertices, normals), False) for edge in mesh_edges(faces))


def selected_edge_lines(vertices, normals, edges):
    return tuple((projected_edge_line(edge, vertices, normals), False) for edge in edges)


def boundary_curve_lines(vertices, normals, loops):
    values = []
    for loop in loops:
        indices = np.asarray(loop + (loop[0],), dtype=np.int32)
        values.append((vertices[indices] + (normals[indices] * 0.017), False))
    return tuple(values)


def materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_CUBE_SKIN", (0.04, 0.055, 0.08)))
    return {"wire": guide_test.material("AF_CUBE_WIRE", (0.02, 0.9, 1.0), 2.0),
            "boundary": guide_test.material("AF_CUBE_BOUNDARY", (1.0, 0.8, 0.03), 2.8),
            "anchor": guide_test.material("AF_CUBE_ANCHOR", (1.0, 0.25, 0.035), 2.5),
            "transition": guide_test.material("AF_CUBE_TRANSITION", (0.25, 1.0, 0.18), 2.8)}


def create_visuals(skin, anchors, vertices, normals, faces, removed, loops, inputs, collection):
    values = materials(skin)
    visuals = {"skin": skin}
    visuals["wire"] = field_test.make_curve("AF_CUBE_WIRE", edge_lines(vertices, normals, faces), collection, values["wire"], 0.0014)
    visuals["cut_wire"] = field_test.make_curve("AF_CUBE_CUT_WIRE", selected_edge_lines(vertices, normals, kept_edges(faces, removed)), collection, values["wire"], 0.0014)
    visuals["boundary"] = field_test.make_curve("AF_CUBE_BOUNDARY", boundary_curve_lines(vertices, normals, loops), collection, values["boundary"], 0.0030)
    visuals["anchors"] = field_test.make_curve("AF_CUBE_ANCHORS", global_test.offset_anchor_lines(anchors, inputs, 0.015), collection, values["anchor"], 0.0036)
    return visuals


def render_specs():
    assembled = {"skin", "hybrid_wire", "anchors", "transitions"}
    return (("front", assembled, (0.0, -8.0, 1.25)),
            ("threequarter", assembled, (4.6, -7.0, 2.8)),
            ("side", assembled, (7.5, 0.0, 1.25)),
            ("back", {"skin", "hybrid_wire"}, (0.0, 8.0, 1.25)))


def prepare_render(visuals):
    for obj in tuple(bpy.context.scene.objects):
        obj.hide_render = obj not in visuals.values()
    guide_test._render_settings()
    camera = guide_test._camera()
    guide_test._lights()
    return camera


def render_all(camera, visuals, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, visible, position in render_specs():
        field_test.set_visible(visuals, visible)
        guide_test._render_view(camera, position, folder / f"{name}.png")
    contact_sheet(folder)


def contact_sheet(folder):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{spec[0]}.png").convert("RGB") for spec in render_specs()]
    labels = ("Welded quad shell + immutable anchors", "All-quad transitions - three-quarter",
              "All-quad transitions - side", "Complete background topology")
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        field_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_cube_shell_comparison.png")


def edge_incidence(faces):
    edges = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)],
                       faces[:, (2, 3)], faces[:, (3, 0)]))
    _unique, counts = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    return counts


def inverted_faces(vertices, normals, faces):
    points = vertices[faces]
    values = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    targets = normals[faces].mean(axis=1)
    return int(np.count_nonzero(np.einsum("ij,ij->i", values, targets) <= 0.0))


def symmetry_error(vertices):
    from scipy.spatial import cKDTree
    reflected = vertices.copy(); reflected[:, 0] *= -1.0
    return float(cKDTree(vertices).query(reflected, workers=-1)[0].max())


def surface_error(vertices, inputs):
    values = [guide_test._nearest(inputs.bvh, vertex) for vertex in vertices]
    return float(max(np.linalg.norm(vertex - np.asarray(hit[0])) for vertex, hit in zip(vertices, values)))


def loop_anchor_counts(loops, vertices, anchors):
    centers = [vertices[np.asarray(loop)].mean(axis=0) for loop in loops]
    values = []
    for anchor in anchors:
        ring = ordered_outer_ring(anchor)
        index = int(np.argmin([np.linalg.norm(center - ring.mean(axis=0)) for center in centers]))
        values.append({"boundary": len(loops[index]), "anchor": len(ring)})
    return values


def matched_boundaries(loops, vertices, anchors):
    pending, values = set(range(len(loops))), []
    for anchor in anchors:
        ring = ordered_outer_ring(anchor)
        index = min(pending, key=lambda item: np.linalg.norm(vertices[np.asarray(loops[item])].mean(axis=0) - ring.mean(axis=0)))
        pending.remove(index)
        values.append((vertices[np.asarray(loops[index])], ring))
    return tuple(values)


def canonical_loop(points):
    index = int(np.argmax(points[:, 2]))
    return np.roll(points, -index, axis=0)


def loop_samples(points, count):
    closed = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    targets = np.linspace(0.0, cumulative[-1], count, endpoint=False)
    indices = np.minimum(np.searchsorted(cumulative, targets, side="right") - 1, len(points) - 1)
    factors = (targets - cumulative[indices]) / np.maximum(lengths[indices], 1.0e-12)
    return closed[indices] + (factors[:, None] * (closed[indices + 1] - closed[indices]))


def alignment_candidates(points):
    values = []
    for oriented in (points, np.vstack((points[0], points[:0:-1]))):
        values.extend(np.roll(oriented, -index, axis=0) for index in range(len(points)))
    return values


def align_loop(reference, points):
    count = 2 * max(len(reference), len(points))
    target = loop_samples(reference, count)
    candidates = alignment_candidates(points)
    costs = [np.linalg.norm(target - loop_samples(candidate, count), axis=1).sum()
             for candidate in candidates]
    return candidates[int(np.argmin(costs))]


def loop_edge_fractions(points):
    closed = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    return np.cumsum(lengths) / np.maximum(lengths.sum(), 1.0e-12)


def balanced_zipper_moves(first, second):
    events = [(value, 1, index) for index, value in enumerate(loop_edge_fractions(first))]
    events.extend((value, 2, index) for index, value in enumerate(loop_edge_fractions(second)))
    events.sort(key=lambda item: (round(float(item[0]), 12), item[1], item[2]))
    return tuple(item[1] for item in events)


def reflection_index_map(points):
    from scipy.spatial import cKDTree
    mirrored = points.copy()
    mirrored[:, 0] *= -1.0
    distances, indices = cKDTree(points).query(mirrored, workers=-1)
    if float(distances.max()) > 1.0e-4:
        raise RuntimeError("Transition vertices are not bilaterally symmetric.")
    return indices.astype(np.int32)


def cyclic_index_path(count, start, end, step):
    values, current = [int(start)], int(start)
    while current != end:
        current = (current + step) % count
        values.append(current)
    return np.asarray(values, dtype=np.int32)


def negative_half_indices(points):
    mapping = reflection_index_map(points)
    fixed = np.flatnonzero(mapping == np.arange(len(points)))
    top = fixed[np.argmax(points[fixed, 2])]
    bottom = fixed[np.argmin(points[fixed, 2])]
    forward = cyclic_index_path(len(points), top, bottom, 1)
    backward = cyclic_index_path(len(points), top, bottom, -1)
    return forward if points[forward, 0].mean() < points[backward, 0].mean() else backward


def open_zipper_moves(first, second):
    first_values = np.cumsum(np.linalg.norm(np.diff(first, axis=0), axis=1))
    second_values = np.cumsum(np.linalg.norm(np.diff(second, axis=0), axis=1))
    first_values /= first_values[-1]
    second_values /= second_values[-1]
    events = [(value, 1) for value in first_values] + [(value, 2) for value in second_values]
    return tuple(item[1] for item in sorted(events, key=lambda item: (round(float(item[0]), 12), item[1])))


def open_zipper_triangles(first, second, moves):
    row, column, values = 0, 0, []
    for move in moves:
        values.append(open_zipper_triangle(first, second, row, column, move))
        row, column = (row + 1, column) if move == 1 else (row, column + 1)
    return tuple(values)


def open_zipper_triangle(first, second, row, column, move):
    if move == 1:
        return (int(first[row]), int(first[row + 1]), int(second[column]))
    return (int(first[row]), int(second[column + 1]), int(second[column]))


def centered_transition_faces(first, second):
    vertices = np.vstack((first, second))
    first_indices = negative_half_indices(first)
    second_indices = negative_half_indices(second) + len(first)
    moves = open_zipper_moves(vertices[first_indices], vertices[second_indices])
    triangles = open_zipper_triangles(first_indices, second_indices, moves)
    expected = expected_transition_boundary(len(first), len(second))
    candidates = symmetric_half_candidates(triangles, reflection_index_map(vertices))
    return next(value for value in candidates if face_boundary_set(value) == expected)


def symmetric_half_candidates(triangles, mapping):
    if len(triangles) % 2 == 0:
        source = paired_quads(triangles)
        return (np.vstack((source, mapping[source][:, ::-1])),)
    return (odd_symmetric_quads(triangles, mapping, True),
            odd_symmetric_quads(triangles, mapping, False))


def odd_symmetric_quads(triangles, mapping, start):
    center_triangle = triangles[0] if start else triangles[-1]
    paired = triangles[1:] if start else triangles[:-1]
    source = paired_quads(paired)
    mirrored = mapping[source][:, ::-1]
    reflected = mapping[np.asarray(center_triangle, dtype=np.int32)]
    center = np.asarray([triangle_pair_quad(center_triangle, reflected)])
    return np.vstack((center, source, mirrored))


def triangle_cost(first, second, third):
    edges = (np.linalg.norm(first - second), np.linalg.norm(second - third), np.linalg.norm(third - first))
    area = 0.5 * np.linalg.norm(np.cross(second - first, third - first))
    return float(area + (0.08 * sum(value * value for value in edges)))


def zipper_dp(first, second):
    rows, columns = len(first), len(second)
    costs = np.full((rows + 1, columns + 1), np.inf)
    moves = np.zeros((rows + 1, columns + 1), dtype=np.int8)
    costs[0, 0] = 0.0
    for row in range(rows + 1):
        for column in range(columns + 1):
            update_zipper_state(row, column, first, second, costs, moves)
    return moves


def update_zipper_state(row, column, first, second, costs, moves):
    if row < len(first):
        value = costs[row, column] + triangle_cost(first[row], first[(row + 1) % len(first)], second[column % len(second)])
        update_dp_cell(row + 1, column, value, 1, costs, moves)
    if column < len(second):
        value = costs[row, column] + triangle_cost(first[row % len(first)], second[(column + 1) % len(second)], second[column])
        update_dp_cell(row, column + 1, value, 2, costs, moves)


def update_dp_cell(row, column, value, move, costs, moves):
    if value < costs[row, column]:
        costs[row, column] = value
        moves[row, column] = move


def zipper_moves(moves):
    row, column = np.asarray(moves.shape) - 1
    values = []
    while row or column:
        move = int(moves[row, column])
        values.append(move)
        row, column = (row - 1, column) if move == 1 else (row, column - 1)
    return tuple(reversed(values))


def zipper_triangles(first_count, second_count, moves):
    row, column, values = 0, 0, []
    for move in moves:
        values.append(zipper_triangle(row, column, move, first_count, second_count))
        row, column = (row + 1, column) if move == 1 else (row, column + 1)
    return tuple(values)


def zipper_triangle(row, column, move, first_count, second_count):
    second = lambda index: first_count + (index % second_count)
    if move == 1:
        return (row % first_count, (row + 1) % first_count, second(column))
    return (row % first_count, second(column + 1), second(column))


def triangle_pair_quad(first, second):
    edges = [tuple(sorted((triangle[index], triangle[(index + 1) % 3])))
             for triangle in (first, second) for index in range(3)]
    unique, counts = np.unique(np.asarray(edges), axis=0, return_counts=True)
    boundary = unique[counts == 1]
    adjacency = boundary_adjacency(boundary)
    return ordered_boundary(int(boundary.min()), adjacency)[0]


def paired_quads(triangles):
    if len(triangles) % 2:
        raise RuntimeError("Transition triangle count must be even.")
    return np.asarray([triangle_pair_quad(triangles[index], triangles[index + 1])
                       for index in range(0, len(triangles), 2)], dtype=np.int32)


def face_boundary_set(faces):
    values = np.vstack([faces[:, (index, (index + 1) % 4)] for index in range(4)])
    unique, counts = np.unique(np.sort(values, axis=1), axis=0, return_counts=True)
    return {tuple(edge) for edge in unique[counts == 1]}


def expected_transition_boundary(first_count, second_count):
    first = {(index, (index + 1) % first_count) for index in range(first_count)}
    second = {(first_count + index, first_count + ((index + 1) % second_count))
              for index in range(second_count)}
    return {tuple(sorted(edge)) for edge in first | second}


def validate_transition_boundary(faces, first_count, second_count):
    expected = expected_transition_boundary(first_count, second_count)
    actual = face_boundary_set(faces)
    if actual != expected:
        print("AF_TRANSITION_DIFF", sorted(actual ^ expected), flush=True)
        raise RuntimeError(f"Transition boundary mismatch: {len(actual ^ expected)} edges.")


def regular_transition_faces(first, second):
    moves = balanced_zipper_moves(first, second)
    triangles = zipper_triangles(len(first), len(second), moves)
    return paired_quads(triangles)


def transition_mesh(name, boundary, anchor):
    first = canonical_loop(boundary)
    second = align_loop(first, anchor)
    vertices = np.vstack((first, second))
    faces = regular_transition_faces(first, second)
    validate_transition_boundary(faces, len(first), len(second))
    return Transition(name, vertices, faces)


def fixed_vertex_count(points):
    mapping = reflection_index_map(points)
    return int(np.count_nonzero(mapping == np.arange(len(points))))


def transition_meshes(loops, vertices, anchors):
    pairs = matched_boundaries(loops, vertices, anchors)
    values = tuple(transition_mesh(anchor.name, boundary, ring)
                   for anchor, (boundary, ring) in zip(anchors, pairs))
    return mirror_eye_transitions(values)


def mirror_eye_transitions(transitions):
    values = list(transitions)
    negative = min(range(len(values)), key=lambda index: values[index].vertices[:, 0].mean())
    positive = max(range(len(values)), key=lambda index: values[index].vertices[:, 0].mean())
    values[positive] = mirrored_transition(values[negative], values[positive])
    return tuple(values)


def mirrored_transition(source, target):
    from scipy.spatial import cKDTree
    points = source.vertices.copy()
    points[:, 0] *= -1.0
    distances, indices = cKDTree(target.vertices).query(points, workers=-1)
    if float(distances.max()) > 1.0e-4:
        raise RuntimeError("Eye transition pair is not bilaterally symmetric.")
    return Transition(target.name, target.vertices, indices[source.faces][:, ::-1])


def transition_lines(transitions, inputs):
    values = []
    for transition in transitions:
        edges = mesh_edges(transition.faces)
        values.extend((raised_transition_edge(edge, transition.vertices, inputs), False) for edge in edges)
    return tuple(values)


def add_transition_visual(visuals, transitions, inputs, collection):
    material = guide_test.material("AF_CUBE_TRANSITION", (0.25, 1.0, 0.18), 2.8)
    lines = transition_lines(transitions, inputs)
    visuals["transitions"] = field_test.make_curve(
        "AF_CUBE_TRANSITIONS", lines, collection, material, 0.0022)


def hybrid_normals(hybrid, inputs):
    hits = [guide_test._nearest(inputs.bvh, point) for point in hybrid.vertices]
    return normalize_rows(np.asarray([hit[1] for hit in hits]))


def add_hybrid_visual(visuals, hybrid, inputs, collection):
    material = guide_test.material("AF_CUBE_HYBRID_WIRE", (0.02, 0.9, 1.0), 2.0)
    normals = hybrid_normals(hybrid, inputs)
    lines = edge_lines(hybrid.vertices, normals, hybrid.faces)
    visuals["hybrid_wire"] = field_test.make_curve(
        "AF_CUBE_HYBRID_WIRE", lines, collection, material, 0.0015)


def raised_transition_edge(edge, vertices, inputs):
    values = np.linspace(0.0, 1.0, 8)
    raw = vertices[edge[0]][None, :] + (values[:, None] * (vertices[edge[1]] - vertices[edge[0]])[None, :])
    hits = [guide_test._nearest(inputs.bvh, point) for point in raw]
    return np.asarray([np.asarray(hit[0]) + (np.asarray(hit[1]) * 0.02) for hit in hits])


def boundary_details(loops, vertices):
    return [{"count": len(loop), "center": vertices[np.asarray(loop)].mean(axis=0).tolist()} for loop in loops]


def transition_metrics(transitions):
    return [transition_metric(item) for item in transitions]


def transition_metric(item):
    incidence = edge_incidence(item.faces)
    edges = mesh_edges(item.faces)
    return {"name": item.name, "vertices": len(item.vertices), "quads": len(item.faces),
            "all_quads": item.faces.shape[1] == 4,
            "euler_characteristic": int(len(item.vertices) - len(edges) + len(item.faces)),
            "boundary_edges": int(np.count_nonzero(incidence == 1)),
            "nonmanifold_edges": int(np.count_nonzero(incidence > 2))}


def hybrid_metrics(hybrid):
    incidence = edge_incidence(hybrid.faces)
    edges = mesh_edges(hybrid.faces)
    return {"vertices": len(hybrid.vertices), "quads": len(hybrid.faces),
            "euler_characteristic": int(len(hybrid.vertices) - len(edges) + len(hybrid.faces)),
            "boundary_edges": int(np.count_nonzero(incidence == 1)),
            "nonmanifold_edges": int(np.count_nonzero(incidence > 2)),
            "edge_symmetry_error": edge_symmetry_error(hybrid)}


def edge_symmetry_error(hybrid):
    from scipy.spatial import cKDTree
    points = hybrid.vertices[mesh_edges(hybrid.faces)].mean(axis=1)
    reflected = points.copy()
    reflected[:, 0] *= -1.0
    return float(cKDTree(points).query(reflected, workers=-1)[0].max())


def metrics_payload(vertices, normals, faces, anchors, inputs, removed, loops, transitions, hybrid):
    incidence = edge_incidence(faces)
    return {"algorithm": "outside_in_cube_base_complex_v1", "vertices": len(vertices),
            "quads": len(faces), "all_quads": faces.shape[1] == 4,
            "boundary_edges": int(np.count_nonzero(incidence == 1)),
            "nonmanifold_edges": int(np.count_nonzero(incidence > 2)),
            "euler_characteristic": int(len(vertices) - len(mesh_edges(faces)) + len(faces)),
            "inverted_faces": inverted_faces(vertices, normals, faces),
            "symmetry_error": symmetry_error(vertices), "surface_error": surface_error(vertices, inputs),
            "removed_faces": int(np.count_nonzero(removed)), "transition_boundaries": len(loops),
            "cut_boundary_edges": len(cut_boundary_edges(faces, removed)),
            "transition_counts": loop_anchor_counts(loops, vertices, anchors),
            "transition_details": boundary_details(loops, vertices), "transition_meshes": transition_metrics(transitions),
            "hybrid_mesh": hybrid_metrics(hybrid),
            "anchor_rows_preserved": sum(len(field_test.object_ring_lines(anchor)) for anchor in anchors)}


def anchor_mesh(anchor):
    vertices = field_test.object_world_vertices(anchor)
    faces = np.asarray([tuple(polygon.vertices) for polygon in anchor.data.polygons], dtype=np.int32)
    if faces.ndim != 2 or faces.shape[1] != 4:
        raise RuntimeError(f"{anchor.name} is not an all-quad annulus.")
    return vertices, faces


def combined_parts(parts):
    vertices, faces, offset = [], [], 0
    for part_vertices, part_faces in parts:
        vertices.append(part_vertices)
        faces.append(part_faces + offset)
        offset += len(part_vertices)
    return np.vstack(vertices), np.vstack(faces)


def welded_hybrid(parts, tolerance):
    vertices, faces = combined_parts(parts)
    keys = np.round(vertices / tolerance).astype(np.int64)
    _unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    remapped = inverse[faces]
    valid = np.asarray([len(set(map(int, face))) == 4 for face in remapped])
    return compact_hybrid(vertices[first], remapped[valid])


def compact_hybrid(vertices, faces):
    used = np.unique(faces)
    inverse = np.full(len(vertices), -1, dtype=np.int32)
    inverse[used] = np.arange(len(used), dtype=np.int32)
    return HybridMesh(vertices[used], inverse[faces])


def build_hybrid(vertices, faces, removed, transitions, anchors, diagonal):
    parts = [(vertices, faces[~removed])]
    parts.extend((item.vertices, item.faces) for item in transitions)
    parts.extend(anchor_mesh(anchor) for anchor in anchors)
    return welded_hybrid(parts, 1.0e-6 * diagonal)


def oriented_cap_faces(ring, normal):
    center = len(ring)
    faces = np.asarray([(center, index, (index + 1) % len(ring))
                        for index in range(len(ring))], dtype=np.int32)
    points = np.vstack((ring, ring.mean(axis=0)))
    value = np.cross(points[faces[0, 1]] - points[center], points[faces[0, 2]] - points[center])
    return faces if np.dot(value, normal) >= 0.0 else faces[:, ::-1]


def cap_part(ring, body_center):
    center, _first, _second, normal = ring_frame(ring)
    if np.dot(normal, center - body_center) < 0.0:
        normal *= -1.0
    vertices = np.vstack((ring, center))
    normals = np.repeat(normal[None, :], len(vertices), axis=0)
    return vertices, oriented_cap_faces(ring, normal), normals


def combine_projection_parts(parts):
    vertices, faces, normals, offset = [], [], [], 0
    for part_vertices, part_faces, part_normals in parts:
        vertices.append(part_vertices)
        faces.append(part_faces + offset)
        normals.append(part_normals)
        offset += len(part_vertices)
    return np.vstack(vertices), np.vstack(faces), normalize_rows(np.vstack(normals))


def capped_field_inputs(proxy, anchors):
    vertices, faces, normals = guide_test.mesh_arrays(proxy)
    center = 0.5 * (vertices.min(axis=0) + vertices.max(axis=0))
    parts = [(vertices, faces, normals)]
    parts.extend(cap_part(ordered_outer_ring(anchor), center) for anchor in anchors)
    vertices, faces, normals = combine_projection_parts(parts)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    bvh = guide_test.surface_bvh(vertices, faces)
    return field_test.FieldInputs(vertices, faces, normals, guide_test.tangent_bases(normals), bvh, diagonal)


def build_shell(args, inputs, collection):
    keys = cube_keys(args.resolution)
    faces = cube_faces(keys, args.resolution)
    vertices, normals = project_cube(keys, args.resolution, inputs)
    vertices, normals = symmetrize_projection(keys, args.resolution, vertices, normals)
    faces = orient_projected_faces(vertices, normals, faces)
    return create_mesh(vertices, faces, collection), vertices, normals, faces


def build_prototype(args):
    _root, skin = guide_test.scene_inputs()
    anchors = field_test.anchor_objects()
    collection = guide_test.make_collection("AF_TOPOLOGY_CUBE_SHELL_TEST")
    proxy = global_test.smooth_proxy(skin, args.target_faces, collection)
    inputs = capped_field_inputs(proxy, anchors)
    shell, vertices, normals, faces = build_shell(args, inputs, collection)
    removed = removed_faces(vertices, faces, anchors, inputs.diagonal)
    loops = boundary_loops(cut_boundary_edges(faces, removed))
    transitions = transition_meshes(loops, vertices, anchors)
    hybrid = build_hybrid(vertices, faces, removed, transitions, anchors, inputs.diagonal)
    create_hybrid_object(hybrid, collection)
    return skin, anchors, collection, inputs, shell, vertices, normals, faces, removed, loops, transitions, hybrid


def finish_prototype(args, data):
    skin, anchors, collection, inputs, shell, vertices, normals, faces, removed, loops, transitions, hybrid = data
    metrics = metrics_payload(vertices, normals, faces, anchors, inputs, removed, loops, transitions, hybrid)
    visuals = create_visuals(skin, anchors, vertices, normals, faces, removed, loops, inputs, collection)
    add_transition_visual(visuals, transitions, inputs, collection)
    add_hybrid_visual(visuals, hybrid, inputs, collection)
    render_all(prepare_render(visuals), visuals, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    shell["af_topology_cube_shell_test"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)
    print("AF_TOPOLOGY_CUBE_SHELL", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
