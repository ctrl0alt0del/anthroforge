import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_guides as guide_test


@dataclass(frozen=True)
class FieldSolution:
    field: np.ndarray
    raw: np.ndarray
    directions: np.ndarray


@dataclass(frozen=True)
class FieldInputs:
    vertices: np.ndarray
    faces: np.ndarray
    normals: np.ndarray
    bases: tuple
    bvh: object
    diagonal: float


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=24000)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def anchor_objects():
    objects = [obj for obj in bpy.data.objects if obj.get("af_topology_annulus_test")]
    return tuple(sorted(objects, key=lambda obj: obj.name))


def open_guides(root):
    return tuple(guide for guide in guide_test.collect_guides(root) if not guide.closed)


def field_inputs(work):
    vertices, faces, normals = guide_test.mesh_arrays(work)
    bvh = guide_test.surface_bvh(vertices, faces)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    return FieldInputs(vertices, faces, normals, guide_test.tangent_bases(normals), bvh, diagonal)


def object_world_vertices(obj):
    return np.asarray([obj.matrix_world @ vertex.co for vertex in obj.data.vertices], dtype=np.float64)


def anchor_polylines(anchors):
    lines = []
    for obj in anchors:
        lines.extend(object_ring_lines(obj))
    return tuple(lines)


def object_ring_lines(obj):
    vertices = object_world_vertices(obj)
    attribute = obj.data.attributes.get("af_topology_ring")
    values = np.asarray([item.value for item in attribute.data], dtype=np.int32)
    return [(vertices[values == ring], True) for ring in sorted(set(values.tolist()))]


def anchor_rows(anchors, inputs):
    rows = []
    for points, closed in anchor_polylines(anchors):
        rows.extend(polyline_rows(points, closed, 5000.0, inputs))
    return tuple(rows)


def guide_rows(guides, anchors, inputs):
    tree = anchor_tree(anchors)
    rows = []
    for guide in guides:
        rows.extend(guide_constraint_rows(guide, tree, inputs))
    return tuple(rows)


def anchor_tree(anchors):
    if not anchors:
        return None
    from scipy.spatial import cKDTree
    points = np.vstack([object_world_vertices(obj) for obj in anchors])
    return cKDTree(points)


def guide_constraint_rows(guide, tree, inputs):
    projected = guide_test.projected_guide(guide, inputs.bvh)
    if projected is None:
        return ()
    keep = guide_keep_mask(projected[0], tree, inputs.diagonal)
    points = projected[0][keep]
    return polyline_rows(points, False, 10.0, inputs) if len(points) > 1 else ()


def guide_keep_mask(points, tree, diagonal):
    if tree is None:
        return np.ones(len(points), dtype=bool)
    return tree.query(points, workers=-1)[0] > diagonal / 90.0


def polyline_rows(points, closed, weight, inputs):
    tangents = guide_test._polyline_tangents(points, closed)
    return tuple(point_constraint(point, tangent, weight, inputs) for point, tangent in zip(points, tangents))


def point_constraint(point, tangent, weight, inputs):
    hit = guide_test._nearest(inputs.bvh, point)
    candidates = inputs.faces[int(hit[2])]
    distances = np.linalg.norm(inputs.vertices[candidates] - point, axis=1)
    index = int(candidates[np.argmin(distances)])
    value = direction_value(tangent, index, inputs)
    return index, value, float(weight)


def direction_value(tangent, index, inputs):
    normal = inputs.normals[index]
    tangent = tangent - (np.dot(tangent, normal) * normal)
    angle = math.atan2(np.dot(tangent, inputs.bases[1][index]), np.dot(tangent, inputs.bases[0][index]))
    return complex(math.cos(4.0 * angle), math.sin(4.0 * angle))


def unique_edges(faces):
    edges = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    return np.unique(np.sort(edges, axis=1), axis=0)


def edge_transport(edges, inputs):
    vectors = inputs.vertices[edges[:, 1]] - inputs.vertices[edges[:, 0]]
    first = edge_angles(vectors, edges[:, 0], inputs)
    second = edge_angles(vectors, edges[:, 1], inputs)
    return np.exp(4.0j * (first - second))


def edge_angles(vectors, indices, inputs):
    first = np.einsum("ij,ij->i", vectors, inputs.bases[0][indices])
    second = np.einsum("ij,ij->i", vectors, inputs.bases[1][indices])
    return np.arctan2(second, first)


def connection_laplacian(inputs):
    from scipy import sparse
    edges = unique_edges(inputs.faces)
    lengths = np.linalg.norm(inputs.vertices[edges[:, 1]] - inputs.vertices[edges[:, 0]], axis=1)
    weights = np.median(lengths) / np.maximum(lengths, 1.0e-9)
    transport = edge_transport(edges, inputs)
    rows, columns, values = connection_entries(edges, weights, transport)
    shape = (len(inputs.vertices),) * 2
    return sparse.coo_matrix((values, (rows, columns)), shape=shape).tocsr()


def connection_entries(edges, weights, transport):
    diagonal = np.concatenate((edges[:, 0], edges[:, 1]))
    rows = np.concatenate((diagonal, edges[:, 0], edges[:, 1]))
    columns = np.concatenate((diagonal, edges[:, 1], edges[:, 0]))
    values = np.concatenate((weights, weights, -weights * transport, -weights * np.conjugate(transport)))
    return rows, columns, values


def solve_field(inputs, rows):
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    weights, targets = constraint_arrays(len(inputs.vertices), rows)
    matrix = connection_laplacian(inputs) + sparse.diags(weights + 1.0e-8)
    raw = spsolve(matrix, targets)
    field = raw / np.maximum(np.abs(raw), 1.0e-12)
    directions = guide_test.field_directions(field, inputs.bases)
    return FieldSolution(field, raw, directions)


def constraint_arrays(count, rows):
    weights = np.zeros(count, dtype=np.float64)
    targets = np.zeros(count, dtype=np.complex128)
    for index, value, weight in rows:
        weights[index] += weight
        targets[index] += weight * value
    if not rows:
        weights[0], targets[0] = 1.0, 1.0 + 0.0j
    return weights, targets


def constraint_conflicts(rows, count):
    weights, targets = constraint_arrays(count, rows)
    conflict = np.zeros(count, dtype=np.float64)
    active = weights > 0.0
    conflict[active] = 1.0 - (np.abs(targets[active]) / weights[active])
    return conflict


def singularity_candidates(solution, inputs, limit=14):
    mask = guide_test.facial_mask(inputs.vertices, inputs.normals)
    order = np.flatnonzero(mask)[np.argsort(np.abs(solution.raw[mask]))]
    return spaced_indices(order, inputs.vertices, inputs.diagonal / 24.0, limit)


def spaced_indices(indices, vertices, radius, limit):
    selected = []
    for index in indices:
        if all(np.linalg.norm(vertices[index] - vertices[other]) > radius for other in selected):
            selected.append(int(index))
        if len(selected) >= limit:
            break
    return np.asarray(selected, dtype=np.int32)


def adjacency_lists(count, faces):
    adjacency = [set() for _index in range(count)]
    for first, second in unique_edges(faces):
        adjacency[int(first)].add(int(second))
        adjacency[int(second)].add(int(first))
    return tuple(tuple(values) for values in adjacency)


def trace_seeds(guides, inputs, limit=18):
    seeds = []
    for guide in guides:
        seed = guide_midpoint_seed(guide, inputs)
        if seed is not None:
            seeds.append(seed)
    step = max(1, int(math.ceil(len(seeds) / limit)))
    return tuple(seeds[::step])


def guide_midpoint_seed(guide, inputs):
    projected = guide_test.projected_guide(guide, inputs.bvh)
    if projected is None or len(projected[0]) < 2:
        return None
    middle = len(projected[0]) // 2
    tangents = guide_test._polyline_tangents(projected[0], False)
    row = point_constraint(projected[0][middle], tangents[middle], 1.0, inputs)
    return row[0], tangents[middle]


def trace_paths(guides, solution, inputs):
    adjacency = adjacency_lists(len(inputs.vertices), inputs.faces)
    mask = guide_test.facial_mask(inputs.vertices, inputs.normals)
    paths = []
    for seed, heading in trace_seeds(guides, inputs):
        paths.append(trace_bidirectional(seed, heading, adjacency, mask, solution, inputs))
    return tuple(path for path in paths if len(path) > 4)


def trace_bidirectional(seed, heading, adjacency, mask, solution, inputs):
    backward = trace_direction(seed, -heading, adjacency, mask, solution, inputs)
    forward = trace_direction(seed, heading, adjacency, mask, solution, inputs)
    return np.vstack((backward[:0:-1], forward))


def trace_direction(seed, heading, adjacency, mask, solution, inputs):
    path, visited, current = [seed], {seed}, seed
    for _step in range(90):
        next_index = trace_step(current, heading, visited, adjacency, mask, solution, inputs)
        if next_index is None:
            break
        heading = inputs.vertices[next_index] - inputs.vertices[current]
        current = next_index
        path.append(current)
        visited.add(current)
    return inputs.vertices[np.asarray(path, dtype=np.int32)]


def trace_step(current, heading, visited, adjacency, mask, solution, inputs):
    candidates = [index for index in adjacency[current] if index not in visited and mask[index]]
    if not candidates:
        return None
    branch = closest_field_branch(solution.directions[current], inputs.normals[current], heading)
    vectors = guide_test._normalize(inputs.vertices[candidates] - inputs.vertices[current])
    scores = vectors @ branch
    best = int(np.argmax(scores))
    return candidates[best] if scores[best] > 0.15 else None


def closest_field_branch(direction, normal, heading):
    second = np.cross(normal, direction)
    branches = np.asarray((direction, -direction, second, -second))
    heading = heading / max(float(np.linalg.norm(heading)), 1.0e-12)
    return branches[int(np.argmax(branches @ heading))]


def offset_paths(paths, inputs, offset):
    result = []
    for path in paths:
        hits = [guide_test._nearest(inputs.bvh, point) for point in path]
        normals = guide_test._normalize(np.asarray([hit[1] for hit in hits]))
        result.append((path + (normals * offset), False))
    return tuple(result)


def marker_lines(indices, inputs, size, offset):
    lines = []
    for index in indices:
        center = inputs.vertices[index] + (inputs.normals[index] * offset)
        first, second = inputs.bases[0][index] * size, inputs.bases[1][index] * size
        lines.extend(((np.asarray((center - first, center + first)), False),
                      (np.asarray((center - second, center + second)), False)))
    return tuple(lines)


def materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_FIELD_SKIN", (0.12, 0.16, 0.21)))
    return {
        "anchor": guide_test.material("AF_FIELD_ANCHOR", (1.0, 0.08, 0.04), 2.0),
        "guide": guide_test.material("AF_FIELD_GUIDE", (1.0, 0.48, 0.03), 1.5),
        "field": guide_test.material("AF_FIELD_CROSS", (0.04, 0.75, 1.0), 1.8),
        "fallback": guide_test.material("AF_FIELD_FALLBACK", (0.68, 0.28, 1.0), 1.8),
        "path": guide_test.material("AF_FIELD_PATH", (0.12, 1.0, 0.28), 2.0),
        "singularity": guide_test.material("AF_FIELD_SINGULARITY", (1.0, 0.78, 0.02), 3.0),
        "conflict": guide_test.material("AF_FIELD_CONFLICT", (1.0, 0.02, 0.72), 3.0),
    }


def make_curve(name, lines, collection, value, bevel):
    return guide_test.curve_object(name, lines, collection, value, bevel)


def field_lines(solution, inputs):
    mask = guide_test.facial_mask(inputs.vertices, inputs.normals)
    return guide_test.cross_lines(inputs.vertices, inputs.normals, solution.directions, mask, 0.05, 0.011, 1000)


def create_visuals(skin, anchors, guides, anchored, fallback, rows, paths, inputs, collection):
    values = materials(skin)
    visuals = {"skin": skin}
    visuals["anchors"] = make_curve("AF_FIELD_ANCHORS", raised_anchors(anchors, inputs), collection, values["anchor"], 0.0035)
    visuals["guides"] = make_curve("AF_FIELD_GUIDES", guide_test.guide_lines(guides, inputs.bvh, 0.008), collection, values["guide"], 0.0022)
    visuals["anchored"] = make_curve("AF_FIELD_ANCHORED", field_lines(anchored, inputs), collection, values["field"], 0.0012)
    visuals["fallback"] = make_curve("AF_FIELD_NO_ANCHORS", field_lines(fallback, inputs), collection, values["fallback"], 0.0012)
    add_diagnostics(visuals, values, anchored, rows, paths, inputs, collection)
    return visuals


def raised_anchors(anchors, inputs):
    lines = []
    for points, closed in anchor_polylines(anchors):
        hits = [guide_test._nearest(inputs.bvh, point) for point in points]
        normals = guide_test._normalize(np.asarray([hit[1] for hit in hits]))
        lines.append((points + (normals * 0.012), closed))
    return tuple(lines)


def add_diagnostics(visuals, values, solution, guide_constraints, paths, inputs, collection):
    conflict_ids = conflict_candidates(guide_constraints, inputs)
    singular = singularity_candidates(solution, inputs)
    visuals["paths"] = make_curve("AF_FIELD_PATHS", offset_paths(paths, inputs, 0.014), collection, values["path"], 0.002)
    visuals["singular"] = make_curve("AF_FIELD_POLES", marker_lines(singular, inputs, 0.022, 0.016), collection, values["singularity"], 0.0025)
    visuals["conflicts"] = make_curve("AF_FIELD_CONFLICTS", marker_lines(conflict_ids, inputs, 0.017, 0.018), collection, values["conflict"], 0.0022)


def conflict_candidates(rows, inputs):
    conflict = constraint_conflicts(rows, len(inputs.vertices))
    active = np.flatnonzero(conflict > 0.3)
    ordered = active[np.argsort(conflict[active])[::-1]]
    return spaced_indices(ordered, inputs.vertices, inputs.diagonal / 28.0, 24)


def render_variants():
    return {
        "inputs": {"skin", "anchors", "guides"},
        "anchored_field": {"skin", "anchors", "guides", "anchored"},
        "no_anchor_field": {"skin", "guides", "fallback"},
        "diagnostics": {"skin", "anchors", "paths", "singular", "conflicts"},
    }


def set_visible(visuals, names):
    for name, obj in visuals.items():
        obj.hide_render = name not in names


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
    variants = render_variants()
    for name, visible in variants.items():
        set_visible(visuals, visible)
        guide_test._render_view(camera, (0.0, -8.0, 1.25), folder / f"{name}_front.png")
    render_threequarter(camera, visuals, variants, folder)
    contact_sheet(folder, tuple(variants))


def render_threequarter(camera, visuals, variants, folder):
    set_visible(visuals, variants["diagnostics"])
    guide_test._render_view(camera, (4.6, -7.0, 2.8), folder / "diagnostics_threequarter.png")


def contact_sheet(folder, names):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{name}_front.png").convert("RGB") for name in names]
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    labels = ("Frozen anchors + open guides", "Anchor-constrained 4-RoSy field",
              "No-anchor fallback field", "Pole candidates + traced paths")
    for index, (image, label) in enumerate(zip(images, labels)):
        paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_field_comparison.png")


def paste_panel(canvas, image, label, index, image_draw):
    x, y = (index % 2) * 720, (index // 2) * 720
    canvas.paste(image, (x, y))
    draw = image_draw.Draw(canvas)
    draw.rectangle((x, y, x + 430, y + 38), fill=(5, 8, 14))
    draw.text((x + 12, y + 10), label, fill=(235, 240, 248))


def alignment_metrics(solution, rows):
    errors = [guide_test._angular_error(solution.field[index], value) for index, value, _weight in rows]
    return {
        "constraints": len(rows),
        "mean_degrees": float(np.degrees(np.mean(errors))) if errors else 0.0,
        "p95_degrees": float(np.degrees(np.quantile(errors, 0.95))) if errors else 0.0,
    }


def field_difference_degrees(first, second, rows):
    indices = np.unique([row[0] for row in rows])
    angles = [guide_test._angular_error(first.field[index], second.field[index]) for index in indices]
    return float(np.degrees(np.mean(angles))) if angles else 0.0


def metrics_payload(anchors, guides, anchor_rows_value, guide_rows_value, fallback_rows, anchored, fallback, paths, inputs):
    conflicts = constraint_conflicts(guide_rows_value, len(inputs.vertices))
    return {
        "anchors": len(anchors), "open_guides": len(guides),
        "vertices": len(inputs.vertices), "triangles": len(inputs.faces),
        "anchor_alignment": alignment_metrics(anchored, anchor_rows_value),
        "guide_alignment_anchored": alignment_metrics(anchored, guide_rows_value),
        "guide_alignment_no_anchors": alignment_metrics(fallback, fallback_rows),
        "anchor_influence_degrees": field_difference_degrees(anchored, fallback, anchor_rows_value),
        "conflict_vertices": int(np.count_nonzero(conflicts > 0.3)),
        "conflict_clusters": len(conflict_candidates(guide_rows_value, inputs)),
        "pole_candidates": len(singularity_candidates(anchored, inputs)),
        "traced_paths": len(paths),
    }


def save_outputs(args, metrics, visuals):
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    visuals["skin"]["af_topology_field_test"] = json.dumps(metrics, sort_keys=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output), copy=True)


def build_prototype(args):
    root, skin = guide_test.scene_inputs()
    anchors, guides = anchor_objects(), open_guides(root)
    collection = guide_test.make_collection("AF_TOPOLOGY_FIELD_TEST")
    work = guide_test.duplicate_work_mesh(skin, args.target_faces, collection)
    inputs = field_inputs(work)
    anchor_values = anchor_rows(anchors, inputs)
    guide_values = guide_rows(guides, anchors, inputs)
    fallback_values = guide_rows(guides, (), inputs)
    anchored = solve_field(inputs, anchor_values + guide_values)
    fallback = solve_field(inputs, fallback_values)
    paths = trace_paths(guides, anchored, inputs)
    return skin, anchors, guides, collection, inputs, anchor_values, guide_values, fallback_values, anchored, fallback, paths


def finish_prototype(args, data):
    skin, anchors, guides, collection, inputs, anchor_values, guide_values, fallback_values, anchored, fallback, paths = data
    metrics = metrics_payload(anchors, guides, anchor_values, guide_values, fallback_values, anchored, fallback, paths, inputs)
    visuals = create_visuals(skin, anchors, guides, anchored, fallback, guide_values, paths, inputs, collection)
    camera = prepare_render(visuals)
    render_all(camera, visuals, args.render_dir)
    save_outputs(args, metrics, visuals)
    print("AF_TOPOLOGY_FIELD_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
