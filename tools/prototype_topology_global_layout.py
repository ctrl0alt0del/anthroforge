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
import prototype_topology_field as field_test
import prototype_topology_guides as guide_test


@dataclass(frozen=True)
class LoopNode:
    name: str
    points: np.ndarray
    screen: np.ndarray
    center: np.ndarray


@dataclass(frozen=True)
class LayoutCurve:
    name: str
    points: np.ndarray
    kind: str


@dataclass(frozen=True)
class MacroEdge:
    start: int
    end: int
    points: np.ndarray


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=32000)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def smooth_proxy(skin, target_faces, collection):
    work = guide_test.duplicate_work_mesh(skin, target_faces, collection)
    modifier = work.modifiers.new("AF_TOPO_SCALE_SMOOTH", "SMOOTH")
    modifier.factor, modifier.iterations = 0.42, 10
    guide_test._activate(work)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return work


def ring_perimeter(points):
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def outer_ring(obj):
    rings = field_test.object_ring_lines(obj)
    return max((points for points, _closed in rings), key=ring_perimeter)


def screen_points(points):
    return np.asarray(points)[:, (0, 2)]


def loop_nodes(anchors):
    values = []
    for anchor in anchors:
        points = outer_ring(anchor)
        screen = screen_points(points)
        values.append(LoopNode(anchor.name, points, screen, screen.mean(axis=0)))
    return tuple(values)


def ellipse_outline(nodes, inputs, count=128):
    bounds = np.vstack((inputs.vertices.min(axis=0), inputs.vertices.max(axis=0)))
    center = np.array((0.0, 0.5 * (bounds[0, 2] + bounds[1, 2])))
    radii = np.array((0.47 * (bounds[1, 0] - bounds[0, 0]), 0.47 * (bounds[1, 2] - bounds[0, 2])))
    angles = np.linspace(0.0, math.tau, count, endpoint=False)
    values = center + np.column_stack((np.cos(angles), np.sin(angles))) * radii
    return fit_outline(values, center, nodes, inputs)


def fit_outline(points, center, nodes, inputs):
    for factor in np.linspace(1.0, 0.72, 15):
        candidate = center + ((points - center) * factor)
        if outline_contains(candidate, center, nodes) and all(front_hit(point, inputs) is not None for point in candidate):
            return candidate
    return points


def outline_contains(outline, center, nodes):
    radii = np.maximum(np.abs(outline - center).max(axis=0), 1.0e-9)
    values = np.vstack([(node.screen - center) / radii for node in nodes])
    return bool(np.max(np.linalg.norm(values, axis=1)) < 0.97)


def front_hit(point, inputs):
    y = float(inputs.vertices[:, 1].min() - inputs.diagonal)
    hit = inputs.bvh.ray_cast(Vector((point[0], y, point[1])), Vector((0.0, 1.0, 0.0)), 3.0 * inputs.diagonal)
    return None if hit[0] is None else (np.asarray(hit[0]), np.asarray(hit[1]))


def project_screen_curve(points, inputs, offset):
    hits = [front_hit(point, inputs) for point in points]
    valid = [hit for hit in hits if hit is not None]
    if len(valid) != len(points):
        return np.empty((0, 3), dtype=np.float64)
    return np.asarray([point + (normal * offset) for point, normal in valid])


def delaunay_pairs(nodes):
    if len(nodes) < 3:
        return tuple((index, index + 1) for index in range(len(nodes) - 1))
    from scipy.spatial import Delaunay
    simplices = Delaunay(np.asarray([node.center for node in nodes])).simplices
    edges = {tuple(sorted((int(face[i]), int(face[(i + 1) % 3])))) for face in simplices for i in range(3)}
    return tuple(sorted(edges))


def normalized(vector):
    return vector / max(float(np.linalg.norm(vector)), 1.0e-12)


def support_point(node, direction, lateral):
    side = np.array((-direction[1], direction[0]))
    relative = node.screen - node.center
    width = np.quantile(np.abs(relative @ side), 0.9)
    target = (relative @ direction) - 4.0 * np.square((relative @ side) - (lateral * width))
    return node.screen[int(np.argmax(target))]


def bezier_path(start, finish, count=32):
    values = np.linspace(0.0, 1.0, count)
    ease = values * values * (3.0 - (2.0 * values))
    return start[None, :] + (ease[:, None] * (finish - start)[None, :])


def corridor_curves(nodes, pairs):
    result = []
    for first, second in pairs:
        result.extend(pair_corridor(nodes[first], nodes[second], first, second))
    return tuple(result)


def pair_corridor(first, second, first_index, second_index):
    direction = normalized(second.center - first.center)
    curves = []
    for side in (-0.42, 0.42):
        start = support_point(first, direction, side)
        finish = support_point(second, -direction, -side)
        curves.append(LayoutCurve(f"pair:{first_index}:{second_index}:{side}", bezier_path(start, finish), "PAIR"))
    return tuple(curves)


def neighbor_directions(nodes, pairs):
    values = [[] for _node in nodes]
    for first, second in pairs:
        direction = normalized(nodes[second].center - nodes[first].center)
        values[first].append(direction)
        values[second].append(-direction)
    return tuple(tuple(item) for item in values)


def direction_set():
    angles = np.linspace(0.0, math.tau, 8, endpoint=False)
    return tuple(np.array((math.cos(angle), math.sin(angle))) for angle in angles)


def direction_is_used(direction, neighbors):
    if not neighbors:
        return False
    return max(float(np.dot(direction, value)) for value in neighbors) > math.cos(math.radians(32.0))


def ray_segment_intersection(origin, direction, first, second):
    edge = second - first
    denominator = cross_2d(direction, edge)
    if abs(denominator) < 1.0e-9:
        return None
    delta = first - origin
    distance, segment = cross_2d(delta, edge) / denominator, cross_2d(delta, direction) / denominator
    return origin + (direction * distance) if distance > 0.0 and 0.0 <= segment <= 1.0 else None


def cross_2d(first, second):
    return float((first[0] * second[1]) - (first[1] * second[0]))


def outline_hit(origin, direction, outline):
    closed = np.vstack((outline, outline[0]))
    hits = [ray_segment_intersection(origin, direction, first, second) for first, second in zip(closed, closed[1:])]
    valid = [hit for hit in hits if hit is not None]
    return min(valid, key=lambda hit: np.linalg.norm(hit - origin)) if valid else None


def spoke_curves(nodes, pairs, outline):
    neighbors = neighbor_directions(nodes, pairs)
    values = []
    for index, node in enumerate(nodes):
        values.extend(node_spokes(index, node, neighbors[index], outline))
    return tuple(values)


def node_spokes(index, node, neighbors, outline):
    outward = normalized(node.center - layout_center(nodes=(node,), neighbors=neighbors))
    result = []
    for slot, direction in enumerate(direction_set()):
        if spoke_direction_allowed(direction, outward, neighbors):
            curve = spoke_curve(index, slot, node, direction, outline)
            if curve is not None:
                result.append(curve)
    return tuple(result)


def layout_center(nodes, neighbors):
    if not neighbors:
        return nodes[0].center - np.array((0.0, 1.0))
    inferred = [nodes[0].center + direction for direction in neighbors]
    return np.mean(inferred, axis=0)


def spoke_direction_allowed(direction, outward, neighbors):
    faces_outward = float(np.dot(direction, outward)) >= -0.05
    return faces_outward and not direction_is_used(direction, neighbors)


def spoke_curve(index, slot, node, direction, outline):
    start = support_point(node, direction, 0.0)
    finish = outline_hit(node.center, direction, outline)
    if finish is None or np.linalg.norm(finish - start) < 1.0e-4:
        return None
    return LayoutCurve(f"spoke:{index}:{slot}", bezier_path(start, finish), "SPOKE")


def layout_curves(nodes, outline):
    pairs = delaunay_pairs(nodes)
    curves = corridor_curves(nodes, pairs) + spoke_curves(nodes, pairs, outline)
    boundary = LayoutCurve("domain", np.vstack((outline, outline[0])), "BOUNDARY")
    return pairs, curves + (boundary,)


def segment_intersection(first, second):
    origin, direction = first[0], first[1] - first[0]
    hit = ray_segment_intersection(origin, direction, second[0], second[1])
    if hit is None:
        return None
    factor = np.dot(hit - origin, direction) / max(np.dot(direction, direction), 1.0e-12)
    return hit if 1.0e-4 < factor < 0.9999 else None


def curve_segments(curve):
    return tuple(zip(curve.points[:-1], curve.points[1:]))


def graph_intersections(curves):
    records = [(index, segment) for index, curve in enumerate(curves) for segment in curve_segments(curve)]
    hits = [segment_intersection(first[1], second[1]) for i, first in enumerate(records) for second in records[i + 1 :] if first[0] != second[0]]
    valid = np.asarray([hit for hit in hits if hit is not None])
    return unique_points(valid, 1.0e-3)


def endpoint_clusters(curves, tolerance=1.0e-4):
    points = np.vstack([(curve.points[0], curve.points[-1]) for curve in curves if curve.kind != "BOUNDARY"])
    unique = unique_points(points, tolerance)
    return unique, nearest_labels(points, unique)


def nearest_labels(points, centers):
    from scipy.spatial import cKDTree
    return np.asarray(cKDTree(centers).query(points)[1], dtype=np.int32)


def route_macro_edges(curves, labels):
    routes = tuple(curve for curve in curves if curve.kind != "BOUNDARY")
    return tuple(MacroEdge(int(labels[2 * index]), int(labels[(2 * index) + 1]), curve.points) for index, curve in enumerate(routes))


def closest_ring(point, rings):
    distances = [np.linalg.norm(ring - point, axis=1).min() for ring in rings]
    return int(np.argmin(distances))


def ring_parameter(point, ring):
    closed = np.vstack((ring, ring[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    records = [segment_parameter(point, first, second) for first, second in zip(closed, closed[1:])]
    index = int(np.argmin([record[0] for record in records]))
    return float((lengths[:index].sum() + (records[index][1] * lengths[index])) / lengths.sum())


def segment_parameter(point, first, second):
    direction = second - first
    factor = np.dot(point - first, direction) / max(np.dot(direction, direction), 1.0e-12)
    factor = float(np.clip(factor, 0.0, 1.0))
    return float(np.linalg.norm(point - (first + (factor * direction)))), factor


def ring_assignments(points, rings):
    return tuple(tuple(np.flatnonzero([closest_ring(point, rings) == index for point in points])) for index in range(len(rings)))


def ring_arc(start, finish, ring):
    count = max(8, int(math.ceil(len(ring) * ((finish - start) % 1.0))))
    parameters = np.linspace(start, start + ((finish - start) % 1.0), count)
    return sample_ring(parameters % 1.0, ring)


def sample_ring(parameters, ring):
    closed = np.vstack((ring, ring[0]))
    cumulative = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))))
    samples = parameters * cumulative[-1]
    return np.column_stack([np.interp(samples, cumulative, closed[:, axis]) for axis in range(2)])


def perimeter_macro_edges(points, rings):
    assignments = ring_assignments(points, rings)
    values = []
    for ring, indices in zip(rings, assignments):
        values.extend(ring_edges(points, indices, ring))
    return tuple(values)


def ring_edges(points, indices, ring):
    ordered = sorted(((ring_parameter(points[index], ring), int(index)) for index in indices))
    if len(ordered) < 2:
        return ()
    cyclic = ordered + [(ordered[0][0] + 1.0, ordered[0][1])]
    return tuple(MacroEdge(first[1], second[1], ring_arc(first[0], second[0], ring)) for first, second in zip(cyclic, cyclic[1:]))


def outgoing_half_edges(edges):
    values = [[] for _index in range(1 + max(max(edge.start, edge.end) for edge in edges))]
    for index, edge in enumerate(edges):
        values[edge.start].append((index, 1))
        values[edge.end].append((index, -1))
    return tuple(tuple(sorted(items, key=lambda item: half_edge_angle(edges[item[0]], item[1]))) for items in values)


def half_edge_points(edge, direction):
    return edge.points if direction > 0 else edge.points[::-1]


def half_edge_angle(edge, direction):
    points = half_edge_points(edge, direction)
    delta = points[1] - points[0]
    return math.atan2(delta[1], delta[0])


def half_edge_end(edge, direction):
    return edge.end if direction > 0 else edge.start


def next_half_edge(current, edges, outgoing):
    index, direction = current
    end = half_edge_end(edges[index], direction)
    reverse = (index, -direction)
    options = outgoing[end]
    return options[(options.index(reverse) - 1) % len(options)]


def trace_face(seed, edges, outgoing):
    cycle, current = [], seed
    for _step in range(4 * len(edges)):
        if current in cycle:
            break
        cycle.append(current)
        current = next_half_edge(current, edges, outgoing)
    return tuple(cycle) if current == seed else ()


def face_cycles(edges):
    outgoing = outgoing_half_edges(edges)
    seeds = {(index, direction) for index in range(len(edges)) for direction in (-1, 1)}
    cycles = []
    while seeds:
        cycle = trace_face(next(iter(seeds)), edges, outgoing)
        seeds.difference_update(cycle)
        if cycle:
            cycles.append(cycle)
    return tuple(cycles)


def cycle_polygon(cycle, edges):
    parts = [half_edge_points(edges[index], direction)[:-1] for index, direction in cycle]
    return np.vstack(parts)


def signed_area(points):
    following = np.roll(points, -1, axis=0)
    return 0.5 * float(np.sum((points[:, 0] * following[:, 1]) - (following[:, 0] * points[:, 1])))


def point_in_polygon(point, polygon):
    first, second = polygon, np.roll(polygon, -1, axis=0)
    crosses = (first[:, 1] > point[1]) != (second[:, 1] > point[1])
    x_hits = (second[:, 0] - first[:, 0]) * (point[1] - first[:, 1])
    x_hits = (x_hits / np.where(np.abs(second[:, 1] - first[:, 1]) < 1.0e-12, 1.0e-12, second[:, 1] - first[:, 1])) + first[:, 0]
    return bool(np.count_nonzero(crosses & (point[0] < x_hits)) % 2)


def exterior_faces(edges, rings):
    polygons = [(cycle, cycle_polygon(cycle, edges)) for cycle in face_cycles(edges)]
    positive = [(cycle, polygon) for cycle, polygon in polygons if signed_area(polygon) > 1.0e-8]
    outside = [(cycle, polygon) for cycle, polygon in positive if not any(point_in_polygon(polygon.mean(axis=0), ring) for ring in rings)]
    return tuple(outside)


def macro_graph(nodes, curves, outline):
    points, labels = endpoint_clusters(curves)
    rings = tuple(node.screen for node in nodes) + (outline,)
    edges = route_macro_edges(curves, labels) + perimeter_macro_edges(points, rings)
    faces = exterior_faces(edges, tuple(node.screen for node in nodes))
    return points, edges, faces


def cycle_vertices(cycle, edges):
    return tuple(edges[index].start if direction > 0 else edges[index].end for index, direction in cycle)


def valid_split_path(start, finish, polygon):
    path = bezier_path(start, finish)
    inside = [point_in_polygon(point, polygon) for point in path[1:-1]]
    return path if all(inside) else None


def face_split_candidates(face, points, edges):
    cycle, polygon = face
    vertices = cycle_vertices(cycle, edges)
    pairs = ((vertices[index], vertices[(index + 3) % 6]) for index in range(3))
    values = [valid_split_path(points[first], points[second], polygon) for first, second in pairs]
    return tuple(path for path in values if path is not None)


def path_symmetry_error(path):
    reflected = path[::-1].copy()
    reflected[:, 0] *= -1.0
    return float(np.max(np.linalg.norm(path - reflected, axis=1)))


def best_face_split(face, points, edges, symmetric):
    candidates = face_split_candidates(face, points, edges)
    if not candidates:
        return None
    score = lambda path: ((path_symmetry_error(path) if symmetric else 0.0), ring_perimeter(path))
    return min(candidates, key=score)


def mirror_face_index(index, faces, used):
    center = faces[index][1].mean(axis=0)
    target = center * np.array((-1.0, 1.0))
    candidates = [item for item in range(len(faces)) if item not in used and item != index]
    return min(candidates, key=lambda item: np.linalg.norm(faces[item][1].mean(axis=0) - target))


def mirrored_path(path):
    value = path.copy()
    value[:, 0] *= -1.0
    return value


def split_hex_faces(faces, points, edges, diagonal):
    hexes = tuple(face for face in faces if len(face[0]) == 6)
    curves, used = [], set()
    for index, face in enumerate(hexes):
        if index not in used:
            curves.extend(split_hex_face(index, hexes, points, edges, diagonal, used))
    return tuple(curves)


def split_hex_face(index, faces, points, edges, diagonal, used):
    center = faces[index][1].mean(axis=0)
    symmetric = abs(center[0]) < diagonal / 1000.0
    path = best_face_split(faces[index], points, edges, symmetric)
    used.add(index)
    if path is None or symmetric:
        return () if path is None else (LayoutCurve(f"split:{index}", path, "SPLIT"),)
    partner = mirror_face_index(index, faces, used)
    used.add(partner)
    return (LayoutCurve(f"split:{index}", path, "SPLIT"),
            LayoutCurve(f"split:{partner}", mirrored_path(path), "SPLIT"))


def optimize_macro_graph(nodes, curves, outline, diagonal):
    points, edges, faces = macro_graph(nodes, curves, outline)
    splits = split_hex_faces(faces, points, edges, diagonal)
    optimized = curves + splits
    final_points, final_edges, final_faces = macro_graph(nodes, optimized, outline)
    return optimized, splits, final_points, final_edges, final_faces


def unique_points(points, tolerance):
    if not len(points):
        return np.empty((0, 2), dtype=np.float64)
    result = []
    for point in points:
        if not result or min(np.linalg.norm(point - value) for value in result) > tolerance:
            result.append(point)
    return np.asarray(result)


def offset_anchor_lines(anchors, inputs, offset):
    lines = []
    for points, closed in field_test.anchor_polylines(anchors):
        screen = screen_points(points)
        projected = project_screen_curve(np.vstack((screen, screen[0])) if closed else screen, inputs, offset)
        lines.append((projected, False))
    return tuple(lines)


def projected_layout(curves, inputs, offset):
    values = []
    for curve in curves:
        points = project_screen_curve(curve.points, inputs, offset)
        if len(points) > 1:
            values.append((points, False))
    return tuple(values)


def marker_lines(points, inputs, size, offset):
    values = []
    for point in points:
        values.extend(marker_cross(point, inputs, size, offset))
    return tuple(values)


def marker_cross(point, inputs, size, offset):
    first = np.asarray((point + (-size, 0.0), point + (size, 0.0)))
    second = np.asarray((point + (0.0, -size), point + (0.0, size)))
    return tuple((project_screen_curve(line, inputs, offset), False) for line in (first, second))


def materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_GLOBAL_SKIN", (0.045, 0.065, 0.09)))
    return {"anchor": guide_test.material("AF_GLOBAL_ANCHOR", (1.0, 0.25, 0.035), 2.0),
            "graph": guide_test.material("AF_GLOBAL_GRAPH", (0.02, 0.9, 1.0), 2.2),
            "split": guide_test.material("AF_GLOBAL_SPLIT", (1.0, 0.82, 0.04), 2.6),
            "border": guide_test.material("AF_GLOBAL_BORDER", (0.3, 1.0, 0.25), 1.8),
            "node": guide_test.material("AF_GLOBAL_NODE", (1.0, 0.9, 0.08), 3.0)}


def create_visuals(skin, anchors, curves, intersections, inputs, collection):
    values = materials(skin)
    inner = tuple(curve for curve in curves if curve.kind not in {"BOUNDARY", "SPLIT"})
    splits = tuple(curve for curve in curves if curve.kind == "SPLIT")
    border = tuple(curve for curve in curves if curve.kind == "BOUNDARY")
    visuals = {"skin": skin}
    visuals["anchors"] = field_test.make_curve("AF_GLOBAL_ANCHORS", offset_anchor_lines(anchors, inputs, 0.009), collection, values["anchor"], 0.0038)
    visuals["graph"] = field_test.make_curve("AF_GLOBAL_GRAPH", projected_layout(inner, inputs, 0.012), collection, values["graph"], 0.0026)
    visuals["splits"] = field_test.make_curve("AF_GLOBAL_SPLITS", projected_layout(splits, inputs, 0.014), collection, values["split"], 0.0030)
    visuals["border"] = field_test.make_curve("AF_GLOBAL_BORDER", projected_layout(border, inputs, 0.011), collection, values["border"], 0.0032)
    visuals["nodes"] = field_test.make_curve("AF_GLOBAL_NODES", marker_lines(intersections, inputs, inputs.diagonal / 220.0, 0.016), collection, values["node"], 0.0022)
    return visuals


def render_specs():
    return (("anchors_front", {"skin", "anchors"}, (0.0, -8.0, 1.25)),
            ("graph_front", {"skin", "anchors", "graph", "splits", "border", "nodes"}, (0.0, -8.0, 1.25)),
            ("graph_threequarter", {"skin", "anchors", "graph", "splits", "border", "nodes"}, (4.6, -7.0, 2.8)),
            ("graph_only", {"anchors", "graph", "splits", "border", "nodes"}, (0.0, -8.0, 1.25)))


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
    labels = ("Immutable authored annuli", "Global block graph - front", "Global block graph - three-quarter", "Abstract graph connectivity")
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        field_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_global_layout_comparison.png")


def symmetry_error(curves):
    points = np.vstack([curve.points for curve in curves])
    mirrored = points.copy()
    mirrored[:, 0] *= -1.0
    from scipy.spatial import cKDTree
    return float(max(cKDTree(points).query(mirrored)[0]))


def metrics_payload(nodes, pairs, curves, intersections, inputs, face_sides, split_count):
    return {"algorithm": "constrained_global_block_graph_v1", "anchors": len(nodes),
            "anchor_rows": sum(len(field_test.object_ring_lines(obj)) for obj in field_test.anchor_objects()),
            "neighbor_pairs": len(pairs), "layout_curves": len(curves),
            "corridor_boundaries": sum(curve.kind == "PAIR" for curve in curves),
            "external_routes": sum(curve.kind == "SPOKE" for curve in curves),
            "junctions": len(intersections), "screen_symmetry_error": symmetry_error(curves),
            "macro_patch_sides": face_sides, "macro_patches": len(face_sides),
            "quadrilateral_macro_patches": sum(value == 4 for value in face_sides),
            "inserted_global_splits": split_count, "all_macro_patches_quadrilateral": all(value == 4 for value in face_sides),
            "proxy_vertices": len(inputs.vertices), "proxy_triangles": len(inputs.faces)}


def build_prototype(args):
    root, skin = guide_test.scene_inputs()
    anchors = field_test.anchor_objects()
    collection = guide_test.make_collection("AF_TOPOLOGY_GLOBAL_LAYOUT_TEST")
    work = smooth_proxy(skin, args.target_faces, collection)
    inputs = field_test.field_inputs(work)
    nodes = loop_nodes(anchors)
    outline = ellipse_outline(nodes, inputs)
    pairs, curves = layout_curves(nodes, outline)
    return skin, anchors, collection, inputs, nodes, pairs, curves


def finish_prototype(args, data):
    skin, anchors, collection, inputs, nodes, pairs, curves = data
    outline = next(curve.points[:-1] for curve in curves if curve.kind == "BOUNDARY")
    curves, splits, _points, _edges, faces = optimize_macro_graph(nodes, curves, outline, inputs.diagonal)
    intersections = graph_intersections(curves)
    face_sides = tuple(len(cycle) for cycle, _polygon in faces)
    metrics = metrics_payload(nodes, pairs, curves, intersections, inputs, face_sides, len(splits))
    visuals = create_visuals(skin, anchors, curves, intersections, inputs, collection)
    render_all(prepare_render(visuals), visuals, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    skin["af_topology_global_layout_test"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)
    print("AF_TOPOLOGY_GLOBAL_LAYOUT", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
