import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_field as field_test
import prototype_topology_global_layout as global_test
import prototype_topology_guides as guide_test


@dataclass(frozen=True)
class Contour:
    family: int
    level: float
    points: np.ndarray
    closed: bool


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=32000)
    parser.add_argument("--levels", type=int, default=7)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def smooth_proxy(skin, target_faces, collection):
    work = guide_test.duplicate_work_mesh(skin, target_faces, collection)
    modifier = work.modifiers.new("AF_MORSE_SCALE_SMOOTH", "SMOOTH")
    modifier.factor, modifier.iterations = 0.48, 12
    guide_test._activate(work)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return work


def pca_axes(vertices):
    centered = vertices - vertices.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov(centered.T))
    return vectors[:, np.argsort(values)[::-1]]


def scalar_axes(vertices):
    symmetry = np.array((1.0, 0.0, 0.0))
    up = np.array((0.0, 0.0, 1.0))
    return symmetry, up


def scalar_levels(values, count):
    quantiles = np.linspace(0.1, 0.9, count)
    return tuple(float(value) for value in np.quantile(values, quantiles))


def unique_edges(faces):
    values = np.vstack((faces[:, (0, 1)], faces[:, (1, 2)], faces[:, (2, 0)]))
    return np.unique(np.sort(values, axis=1), axis=0)


def edge_lookup(edges):
    return {tuple(map(int, edge)): index for index, edge in enumerate(edges)}


def face_edge_ids(faces, lookup):
    return np.asarray([[lookup[tuple(sorted((int(face[i]), int(face[(i + 1) % 3]))))]
                        for i in range(3)] for face in faces], dtype=np.int32)


def crossing_mask(edges, values, level):
    first, second = values[edges[:, 0]] - level, values[edges[:, 1]] - level
    return (first * second) < 0.0


def crossing_points(vertices, edges, values, level, mask):
    selected = edges[mask]
    first, second = values[selected[:, 0]], values[selected[:, 1]]
    factor = ((level - first) / (second - first))[:, None]
    return vertices[selected[:, 0]] + (factor * (vertices[selected[:, 1]] - vertices[selected[:, 0]]))


def contour_adjacency(face_edges, crossed):
    adjacency = {int(index): [] for index in np.flatnonzero(crossed)}
    for edges in face_edges:
        active = tuple(int(edge) for edge in edges if crossed[edge])
        if len(active) == 2:
            adjacency[active[0]].append(active[1])
            adjacency[active[1]].append(active[0])
    return adjacency


def ordered_component(start, adjacency):
    order, previous, current = [], -1, int(start)
    for _step in range(len(adjacency) + 1):
        if current in order or current < 0:
            break
        order.append(current)
        options = [item for item in adjacency[current] if item != previous]
        previous, current = current, options[0] if options else -1
    return tuple(order), current == start


def contour_components(adjacency):
    pending, values = set(adjacency), []
    while pending:
        component = ordered_component(min(pending), adjacency)
        pending.difference_update(component[0])
        if len(component[0]) > 2:
            values.append(component)
    return tuple(values)


def component_points(component, crossed_indices, points):
    lookup = {int(edge): index for index, edge in enumerate(crossed_indices)}
    return points[np.asarray([lookup[int(edge)] for edge in component], dtype=np.int32)]


def contours_at_level(family, level, vertices, edges, face_edges, values):
    crossed = crossing_mask(edges, values, level)
    points = crossing_points(vertices, edges, values, level, crossed)
    indices = np.flatnonzero(crossed)
    adjacency = contour_adjacency(face_edges, crossed)
    return tuple(Contour(family, level, component_points(order, indices, points), closed)
                 for order, closed in contour_components(adjacency))


def contour_length(contour):
    points = np.vstack((contour.points, contour.points[0])) if contour.closed else contour.points
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def useful_contours(contours, diagonal):
    return tuple(contour for contour in contours if contour_length(contour) > diagonal * 0.18)


def contour_families(inputs, level_count):
    edges = unique_edges(inputs.faces)
    face_edges = face_edge_ids(inputs.faces, edge_lookup(edges))
    axes = scalar_axes(inputs.vertices)
    values = tuple(inputs.vertices @ axis for axis in axes)
    families = tuple(family_contours(index, field, inputs, edges, face_edges, level_count)
                     for index, field in enumerate(values))
    return axes, values, families


def family_contours(index, values, inputs, edges, face_edges, level_count):
    contours = [contour for level in scalar_levels(values, level_count)
                for contour in contours_at_level(index, level, inputs.vertices, edges, face_edges, values)]
    return useful_contours(contours, inputs.diagonal)


def anchor_tree(anchors):
    from scipy.spatial import cKDTree
    points = np.vstack([field_test.object_world_vertices(anchor) for anchor in anchors])
    return cKDTree(points)


def cyclic_runs(mask):
    if mask.all():
        return (np.arange(len(mask)),)
    start = int(np.flatnonzero(~mask)[0])
    order = np.roll(np.arange(len(mask)), -(start + 1))
    return linear_true_runs(order, mask)


def linear_true_runs(order, mask):
    runs, current = [], []
    for index in order:
        if mask[index]:
            current.append(int(index))
        elif current:
            runs.append(np.asarray(current)); current = []
    if current:
        runs.append(np.asarray(current))
    return tuple(run for run in runs if len(run) > 1)


def clip_contour(contour, tree, clearance):
    distances = tree.query(contour.points, workers=-1)[0]
    mask = distances > clearance
    if mask.all():
        return (np.vstack((contour.points, contour.points[0])),), ()
    parts = tuple(contour.points[run] for run in cyclic_runs(mask))
    valid = tuple(part for part in parts if len(part) > 1)
    endpoints = tuple(point for part in valid for point in (part[0], part[-1]))
    return valid, endpoints


def clipped_families(families, anchors, diagonal):
    tree, endpoints = anchor_tree(anchors), []
    result = []
    for family in families:
        records = [clip_contour(contour, tree, diagonal / 55.0) for contour in family]
        parts = [part for values, _ends in records for part in values]
        endpoints.extend(point for _values, ends in records for point in ends)
        result.append(tuple(parts))
    return tuple(result), np.asarray(endpoints)


def outer_rings(anchors):
    return tuple(global_test.outer_ring(anchor) for anchor in anchors)


def endpoint_ring_groups(endpoints, rings):
    from scipy.spatial import cKDTree
    distances = np.column_stack([cKDTree(ring).query(endpoints, workers=-1)[0] for ring in rings])
    owners = np.argmin(distances, axis=1)
    return tuple(np.flatnonzero(owners == index) for index in range(len(rings)))


def assigned_ring_targets(endpoints, ring):
    from scipy.optimize import linear_sum_assignment
    costs = np.linalg.norm(endpoints[:, None, :] - ring[None, :, :], axis=2)
    rows, columns = linear_sum_assignment(costs)
    targets = np.empty_like(endpoints)
    targets[rows] = ring[columns]
    return targets


def project_path(start, finish, inputs, count=20):
    values = np.linspace(0.0, 1.0, count)
    ease = values * values * (3.0 - (2.0 * values))
    raw = start[None, :] + (ease[:, None] * (finish - start)[None, :])
    hits = [guide_test._nearest(inputs.bvh, point) for point in raw]
    return np.asarray([hit[0] for hit in hits])


def transition_paths(endpoints, anchors, inputs):
    rings, paths = outer_rings(anchors), []
    for indices, ring in zip(endpoint_ring_groups(endpoints, rings), rings):
        if len(indices):
            targets = assigned_ring_targets(endpoints[indices], ring)
            paths.extend(project_path(start, finish, inputs) for start, finish in zip(endpoints[indices], targets))
    return tuple(paths)


def transition_intersections(paths):
    curves = tuple(global_test.LayoutCurve(str(index), path[:, (0, 2)], "TRANSITION")
                   for index, path in enumerate(paths))
    return len(global_test.graph_intersections(curves))


def transition_symmetry_error(paths):
    if not paths:
        return 0.0
    points = np.vstack(paths)
    reflected = points.copy(); reflected[:, 0] *= -1.0
    from scipy.spatial import cKDTree
    return float(cKDTree(points).query(reflected, workers=-1)[0].max())


def raised_line(points, inputs, offset, closed):
    values = np.vstack((points, points[0])) if closed else points
    hits = [guide_test._nearest(inputs.bvh, point) for point in values]
    return np.asarray([np.asarray(hit[0]) + (np.asarray(hit[1]) * offset) for hit in hits])


def raised_contours(contours, inputs, offset):
    return tuple((raised_line(contour.points, inputs, offset, contour.closed), False) for contour in contours)


def raised_parts(parts, inputs, offset):
    return tuple((raised_line(points, inputs, offset, False), False) for points in parts)


def materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_MORSE_SKIN", (0.04, 0.055, 0.08)))
    return {"first": guide_test.material("AF_MORSE_FIRST", (0.02, 0.9, 1.0), 2.2),
            "second": guide_test.material("AF_MORSE_SECOND", (0.9, 0.12, 1.0), 2.2),
            "transition": guide_test.material("AF_MORSE_TRANSITION", (1.0, 0.78, 0.02), 2.8),
            "anchor": guide_test.material("AF_MORSE_ANCHOR", (1.0, 0.25, 0.035), 2.4),
            "endpoint": guide_test.material("AF_MORSE_ENDPOINT", (1.0, 0.88, 0.04), 3.0)}


def create_visuals(skin, anchors, families, clipped, endpoints, transitions, inputs, collection):
    values = materials(skin)
    visuals = {"skin": skin}
    visuals["first"] = field_test.make_curve("AF_MORSE_FIRST", raised_contours(families[0], inputs, 0.011), collection, values["first"], 0.0022)
    visuals["second"] = field_test.make_curve("AF_MORSE_SECOND", raised_contours(families[1], inputs, 0.012), collection, values["second"], 0.0022)
    visuals["cut_first"] = field_test.make_curve("AF_MORSE_CUT_FIRST", raised_parts(clipped[0], inputs, 0.014), collection, values["first"], 0.0026)
    visuals["cut_second"] = field_test.make_curve("AF_MORSE_CUT_SECOND", raised_parts(clipped[1], inputs, 0.015), collection, values["second"], 0.0026)
    visuals["transitions"] = field_test.make_curve("AF_MORSE_TRANSITIONS", raised_parts(transitions, inputs, 0.018), collection, values["transition"], 0.0030)
    visuals["anchors"] = field_test.make_curve("AF_MORSE_ANCHORS", global_test.offset_anchor_lines(anchors, inputs, 0.017), collection, values["anchor"], 0.0037)
    screen = endpoints[:, (0, 2)] if len(endpoints) else np.empty((0, 2))
    visuals["endpoints"] = field_test.make_curve("AF_MORSE_ENDPOINTS", global_test.marker_lines(screen, inputs, inputs.diagonal / 210.0, 0.02), collection, values["endpoint"], 0.0022)
    return visuals


def render_specs():
    uncut = {"skin", "first", "second", "anchors"}
    cut = {"skin", "cut_first", "cut_second", "transitions", "anchors", "endpoints"}
    return (("uncut_front", uncut, (0.0, -8.0, 1.25)),
            ("anchor_cut_front", cut, (0.0, -8.0, 1.25)),
            ("anchor_cut_threequarter", cut, (4.6, -7.0, 2.8)),
            ("complete_back", {"skin", "first", "second"}, (0.0, 8.0, 1.25)))


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
    labels = ("Two complete-shell scalar families", "Hard anchors cut the automatic grid",
              "Anchor transition zones - three-quarter", "Automatic grid covers the back")
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        field_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_morse_grid_comparison.png")


def family_metrics(families):
    return tuple({"contours": len(family), "closed": sum(contour.closed for contour in family),
                  "lengths": [contour_length(contour) for contour in family]} for family in families)


def face_pairs(faces):
    owners = {}
    for face_index, face in enumerate(faces):
        for first, second in zip(face, np.roll(face, -1)):
            owners.setdefault(tuple(sorted((int(first), int(second)))), []).append(face_index)
    return tuple(values for values in owners.values() if len(values) == 2)


def face_grid_labels(inputs, axes, level_count):
    centers = inputs.vertices[inputs.faces].mean(axis=1)
    fields = tuple(centers @ axis for axis in axes)
    levels = tuple(scalar_levels(inputs.vertices @ axis, level_count) for axis in axes)
    bins = tuple(np.searchsorted(level, field) for field, level in zip(fields, levels))
    return (bins[0] * (level_count + 1)) + bins[1]


def component_labels(labels, pairs):
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    active = [(first, second) for first, second in pairs if labels[first] == labels[second]]
    rows = np.asarray([value for pair in active for value in pair], dtype=np.int32)
    cols = np.asarray([value for pair in active for value in pair[::-1]], dtype=np.int32)
    graph = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(labels),) * 2)
    return connected_components(graph, directed=False, return_labels=True)


def component_side_counts(components, pairs, count):
    neighbors = [set() for _index in range(count)]
    for first, second in pairs:
        left, right = int(components[first]), int(components[second])
        if left != right:
            neighbors[left].add(right); neighbors[right].add(left)
    return tuple(len(values) for values in neighbors)


def background_cells(inputs, axes, level_count):
    pairs = face_pairs(inputs.faces)
    labels = face_grid_labels(inputs, axes, level_count)
    count, components = component_labels(labels, pairs)
    sides = component_side_counts(components, pairs, count)
    return {"cells": count, "side_counts": sides, "four_neighbor_cells": sum(value == 4 for value in sides)}


def metrics_payload(inputs, axes, families, clipped, endpoints, transitions, anchors, level_count):
    return {"algorithm": "surface_scalar_grid_v1", "proxy_vertices": len(inputs.vertices),
            "proxy_triangles": len(inputs.faces), "axes": [axis.tolist() for axis in axes],
            "families": family_metrics(families), "clipped_parts": [len(parts) for parts in clipped],
            "anchor_transition_endpoints": len(endpoints),
            "transition_paths": len(transitions), "transition_crossings": transition_intersections(transitions),
            "transition_symmetry_error": transition_symmetry_error(transitions),
            "background_cells": background_cells(inputs, axes, level_count),
            "anchor_rows_preserved": sum(len(field_test.object_ring_lines(anchor)) for anchor in anchors),
            "complete_shell": all(contour.closed for family in families for contour in family)}


def build_prototype(args):
    _root, skin = guide_test.scene_inputs()
    anchors = field_test.anchor_objects()
    collection = guide_test.make_collection("AF_TOPOLOGY_MORSE_GRID_TEST")
    proxy = smooth_proxy(skin, args.target_faces, collection)
    inputs = field_test.field_inputs(proxy)
    axes, _values, families = contour_families(inputs, args.levels)
    clipped, endpoints = clipped_families(families, anchors, inputs.diagonal)
    transitions = transition_paths(endpoints, anchors, inputs)
    return skin, anchors, collection, inputs, axes, families, clipped, endpoints, transitions


def finish_prototype(args, data):
    skin, anchors, collection, inputs, axes, families, clipped, endpoints, transitions = data
    metrics = metrics_payload(inputs, axes, families, clipped, endpoints, transitions, anchors, args.levels)
    visuals = create_visuals(skin, anchors, families, clipped, endpoints, transitions, inputs, collection)
    render_all(prepare_render(visuals), visuals, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    skin["af_topology_morse_grid_test"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)
    print("AF_TOPOLOGY_MORSE_GRID", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
