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
class FaceField:
    centers: np.ndarray
    normals: np.ndarray
    first: np.ndarray
    second: np.ndarray


@dataclass(frozen=True)
class TraceSeed:
    point: np.ndarray
    face: int
    heading: np.ndarray
    source: str


@dataclass(frozen=True)
class TraceResult:
    points: np.ndarray
    reason: str
    source: str


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=48000)
    parser.add_argument("--full-surface", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def face_field(solution, inputs):
    triangles = inputs.vertices[inputs.faces]
    centers = triangles.mean(axis=1)
    normals = face_normals(triangles)
    bases = guide_test.tangent_bases(normals)
    values = vertex_values_in_faces(solution, inputs, normals, bases)
    angles = np.angle(np.mean(values, axis=1)) * 0.25
    first = guide_test._normalize((np.cos(angles)[:, None] * bases[0]) + (np.sin(angles)[:, None] * bases[1]))
    return FaceField(centers, normals, first, guide_test._normalize(np.cross(normals, first)))


def face_normals(triangles):
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return guide_test._normalize(normals)


def vertex_values_in_faces(solution, inputs, normals, bases):
    directions = solution.directions[inputs.faces]
    projected = directions - (np.einsum("fvi,fi->fv", directions, normals)[:, :, None] * normals[:, None, :])
    projected = projected / np.maximum(np.linalg.norm(projected, axis=2)[:, :, None], 1.0e-12)
    first = np.einsum("fvi,fi->fv", projected, bases[0])
    second = np.einsum("fvi,fi->fv", projected, bases[1])
    return np.exp(4.0j * np.arctan2(second, first))


def incident_faces(vertex_count, faces):
    result = [[] for _index in range(vertex_count)]
    for face_index, face in enumerate(faces):
        for vertex in face:
            result[int(vertex)].append(face_index)
    return tuple(tuple(values) for values in result)


def singularities(solution, face_values, inputs, facial_only=True):
    incident = incident_faces(len(inputs.vertices), inputs.faces)
    mask = singularity_mask(inputs, facial_only)
    records = [vertex_winding(index, incident[index], face_values, inputs) for index in np.flatnonzero(mask)]
    records = [(index, winding) for index, winding in records if winding]
    return cluster_singularities(records, inputs)


def singularity_mask(inputs, facial_only):
    if facial_only:
        return guide_test.facial_mask(inputs.vertices, inputs.normals)
    return np.ones(len(inputs.vertices), dtype=bool)


def vertex_winding(index, faces, face_values, inputs):
    if len(faces) < 3:
        return int(index), 0
    order = ordered_incident_faces(index, faces, face_values.centers, inputs)
    values = face_cross_values(index, order, face_values.first, inputs)
    changes = np.angle(np.roll(values, -1) * np.conjugate(values))
    return int(index), int(np.rint(changes.sum() / (2.0 * math.pi)))


def ordered_incident_faces(index, faces, centers, inputs):
    vectors = centers[list(faces)] - inputs.vertices[index]
    first = vectors @ inputs.bases[0][index]
    second = vectors @ inputs.bases[1][index]
    order = np.argsort(np.arctan2(second, first))
    return tuple(np.asarray(faces, dtype=np.int32)[order].tolist())


def face_cross_values(index, faces, directions, inputs):
    values = []
    for face in faces:
        direction = tangent_projection(directions[face], inputs.normals[index])
        angle = math.atan2(np.dot(direction, inputs.bases[1][index]), np.dot(direction, inputs.bases[0][index]))
        values.append(complex(math.cos(4.0 * angle), math.sin(4.0 * angle)))
    return np.asarray(values)


def tangent_projection(vector, normal):
    projected = vector - (np.dot(vector, normal) * normal)
    return projected / max(float(np.linalg.norm(projected)), 1.0e-12)


def cluster_singularities(records, inputs):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    if not records:
        return ()
    points = inputs.vertices[[record[0] for record in records]]
    pairs = np.asarray(list(spatial_pairs(points, inputs.diagonal / 55.0)), dtype=np.int32)
    rows, columns = symmetric_pairs(pairs, len(records))
    graph = coo_matrix((np.ones(len(rows)), (rows, columns)), shape=(len(records), len(records)))
    count, labels = connected_components(graph, directed=False)
    clusters = [cluster_record(records, points, labels, label) for label in range(count)]
    return tuple(record for record in clusters if record is not None)


def mirror_records(records, inputs):
    from scipy.spatial import cKDTree
    tree = cKDTree(inputs.vertices)
    output = list(records)
    for index, winding in records:
        point = inputs.vertices[index].copy()
        point[0] *= -1.0
        output.append((int(tree.query(point)[1]), winding))
    return tuple(dict.fromkeys(output))


def spatial_pairs(points, radius):
    from scipy.spatial import cKDTree
    return cKDTree(points).query_pairs(radius)


def symmetric_pairs(pairs, count):
    diagonal = np.arange(count, dtype=np.int32)
    if not len(pairs):
        return diagonal, diagonal
    rows = np.concatenate((pairs[:, 0], pairs[:, 1], diagonal))
    columns = np.concatenate((pairs[:, 1], pairs[:, 0], diagonal))
    return rows, columns


def cluster_record(records, points, labels, label):
    members = np.flatnonzero(labels == label)
    winding = int(sum(records[index][1] for index in members))
    if not winding:
        return None
    center = points[members].mean(axis=0)
    representative = members[np.argmin(np.linalg.norm(points[members] - center, axis=1))]
    return int(records[representative][0]), int(np.sign(winding))


def face_adjacency(faces):
    neighbors = np.full((len(faces), 3), -1, dtype=np.int32)
    neighbor_slots = np.full((len(faces), 3), -1, dtype=np.int32)
    pending = {}
    for face_index, face in enumerate(faces):
        connect_face_edges(face_index, face, pending, neighbors, neighbor_slots)
    return neighbors, neighbor_slots


def connect_face_edges(face_index, face, pending, neighbors, neighbor_slots):
    for slot, edge in enumerate(((face[0], face[1]), (face[1], face[2]), (face[2], face[0]))):
        key = tuple(sorted((int(edge[0]), int(edge[1]))))
        if key in pending:
            other_face, other_slot = pending.pop(key)
            neighbors[face_index, slot], neighbors[other_face, other_slot] = other_face, face_index
            neighbor_slots[face_index, slot], neighbor_slots[other_face, other_slot] = other_slot, slot
        else:
            pending[key] = face_index, slot


def outer_ring_points(obj):
    return max(ring_point_sets(obj), key=closed_perimeter)


def ring_point_sets(obj):
    vertices = field_test.object_world_vertices(obj)
    attribute = obj.data.attributes.get("af_topology_ring")
    rings = np.asarray([item.value for item in attribute.data], dtype=np.int32)
    return tuple(vertices[rings == ring] for ring in np.unique(rings))


def boundary_ring_points(obj):
    candidates = ring_point_sets(obj)
    return min(candidates, key=closed_perimeter), max(candidates, key=closed_perimeter)


def closed_perimeter(points):
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def anchor_seeds(anchors, inputs):
    seeds = []
    for obj in anchors:
        points = outer_ring_points(obj)
        seeds.extend(ring_seeds(obj.name, points, inputs))
    return tuple(seeds)


def half_domain_seeds(seeds, inputs):
    tolerance = inputs.diagonal / 1000.0
    return tuple(seed for seed in seeds if seed.point[0] >= -tolerance)


def ring_seeds(name, points, inputs):
    count = min(8, max(4, len(points) // 6))
    indices = np.linspace(0, len(points), count, endpoint=False, dtype=np.int32)
    tangents = guide_test._polyline_tangents(points, True)
    center = points.mean(axis=0)
    return tuple(anchor_seed(name, points, tangents, center, int(index), inputs) for index in indices)


def anchor_seed(name, points, tangents, center, index, inputs):
    hit = guide_test._nearest(inputs.bvh, points[index])
    normal = np.asarray(hit[1])
    side = tangent_projection(np.cross(normal, tangents[index]), normal)
    side *= 1.0 if np.dot(side, points[index] - center) >= 0.0 else -1.0
    point = np.asarray(hit[0]) + (side * inputs.diagonal / 10000.0)
    return TraceSeed(point, int(hit[2]), side, f"anchor:{name}")


def singularity_seeds(records, face_values, inputs):
    incident = incident_faces(len(inputs.vertices), inputs.faces)
    seeds = []
    for index, winding in records:
        seeds.extend(singularity_ports(index, winding, incident[index], face_values, inputs))
    return tuple(seeds)


def singularity_ports(index, winding, faces, face_values, inputs):
    candidates = []
    for face in faces:
        candidates.extend(face_vertex_ports(index, face, face_values, inputs))
    ports = deduplicate_ports(candidates)
    expected = min(len(ports), max(3, 4 - winding))
    return tuple(ports[:expected])


def face_vertex_ports(index, face, face_values, inputs):
    point = inputs.vertices[index]
    scale = inputs.diagonal / 10000.0
    branches = face_branches(face_values, face)
    valid = [branch for branch in branches if point_in_face(point + (branch * scale), face, inputs)]
    return [TraceSeed(point + (branch * scale), face, branch, f"singularity:{index}") for branch in valid]


def face_branches(face_values, face):
    first, second = face_values.first[face], face_values.second[face]
    return (first, -first, second, -second)


def point_in_face(point, face, inputs):
    triangle = inputs.vertices[inputs.faces[face]]
    barycentric = barycentric_coordinates(point, triangle)
    return bool(np.all(barycentric >= -1.0e-5))


def barycentric_coordinates(point, triangle):
    first, second = triangle[1] - triangle[0], triangle[2] - triangle[0]
    relative = point - triangle[0]
    matrix = np.asarray(((np.dot(first, first), np.dot(first, second)),
                         (np.dot(first, second), np.dot(second, second))))
    uv = np.linalg.solve(matrix, np.asarray((np.dot(relative, first), np.dot(relative, second))))
    return np.asarray((1.0 - uv.sum(), uv[0], uv[1]))


def deduplicate_ports(seeds):
    result = []
    for seed in seeds:
        if not any(np.dot(seed.heading, other.heading) > math.cos(math.radians(20.0)) for other in result):
            result.append(seed)
    return result


def trace_all(seeds, face_values, adjacency, inputs, anchor_points, facial_only=True):
    from scipy.spatial import cKDTree
    anchor_tree = cKDTree(anchor_points)
    registry, results = [], []
    for seed in seeds:
        tree = cKDTree(np.vstack(registry)) if registry else None
        result = trace_seed(seed, face_values, adjacency, inputs, anchor_tree, tree, facial_only)
        if len(result.points) > 4:
            results.append(result)
            registry.append(result.points[::2])
    return tuple(results)


def symmetric_results(results):
    output = []
    for result in results:
        output.extend(mirror_trace(result))
    return tuple(output)


def mirror_trace(result):
    mirrored = result.points.copy()
    mirrored[:, 0] *= -1.0
    if result.reason == "symmetry_plane":
        joined = np.vstack((mirrored[:-1], result.points[::-1]))
        return (TraceResult(joined, "symmetry_join", result.source),)
    return (result, TraceResult(mirrored, result.reason, f"{result.source}:mirror"))


def trace_seed(seed, face_values, adjacency, inputs, anchor_tree, registry, facial_only=True):
    points, visited = [seed.point], set()
    point, face, entry, heading = seed.point, seed.face, -1, seed.heading
    for step in range(600):
        state = trace_state(point, face, entry, heading, face_values, adjacency, inputs)
        if state is None:
            return TraceResult(np.asarray(points), "surface_boundary", seed.source)
        point, face, entry, heading, branch = state
        point = clip_symmetry_crossing(points[-1], point)
        points.append(point)
        reason = stopping_reason(point, face, branch, step, visited, anchor_tree, registry, inputs, facial_only)
        if reason:
            return TraceResult(np.asarray(points), reason, seed.source)
        visited.add((face, branch))
    return TraceResult(np.asarray(points), "step_limit", seed.source)


def clip_symmetry_crossing(previous, point):
    if point[0] > 0.0 or previous[0] <= 0.0:
        return point
    factor = previous[0] / max(previous[0] - point[0], 1.0e-12)
    return previous + (factor * (point - previous))


def trace_state(point, face, entry, heading, face_values, adjacency, inputs):
    direction, branch = select_branch(face, heading, face_values)
    crossing = triangle_crossing(point, direction, face, entry, inputs)
    if crossing is None:
        return None
    next_point, slot = crossing
    next_face = int(adjacency[0][face, slot])
    if next_face < 0:
        return None
    next_entry = int(adjacency[1][face, slot])
    return next_point, next_face, next_entry, direction, branch


def select_branch(face, heading, face_values):
    branches = np.asarray(face_branches(face_values, face))
    heading = heading / max(float(np.linalg.norm(heading)), 1.0e-12)
    index = int(np.argmax(branches @ heading))
    return branches[index], index


def triangle_crossing(point, direction, face, entry, inputs):
    triangle = inputs.vertices[inputs.faces[face]]
    basis = face_plane_basis(triangle)
    origin, ray = project_2d(point, triangle[0], basis), project_vector_2d(direction, basis)
    hits = [edge_intersection(origin, ray, project_2d(triangle[i], triangle[0], basis),
                              project_2d(triangle[(i + 1) % 3], triangle[0], basis), i) for i in range(3)]
    valid = [hit for hit in hits if hit is not None and hit[1] != entry]
    if not valid:
        return None
    distance, slot = min(valid)
    return point + (direction * distance), slot


def face_plane_basis(triangle):
    first = triangle[1] - triangle[0]
    first /= max(float(np.linalg.norm(first)), 1.0e-12)
    normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
    normal /= max(float(np.linalg.norm(normal)), 1.0e-12)
    return first, np.cross(normal, first)


def project_2d(point, origin, basis):
    relative = point - origin
    return np.asarray((np.dot(relative, basis[0]), np.dot(relative, basis[1])))


def project_vector_2d(vector, basis):
    return np.asarray((np.dot(vector, basis[0]), np.dot(vector, basis[1])))


def edge_intersection(origin, ray, first, second, slot):
    edge = second - first
    denominator = cross_2d(ray, edge)
    if abs(denominator) < 1.0e-12:
        return None
    relative = first - origin
    distance = cross_2d(relative, edge) / denominator
    factor = cross_2d(relative, ray) / denominator
    return (float(distance), slot) if distance > 1.0e-7 and -1.0e-7 <= factor <= 1.0 + 1.0e-7 else None


def cross_2d(first, second):
    return float((first[0] * second[1]) - (first[1] * second[0]))


def stopping_reason(point, face, branch, step, visited, anchor_tree, registry, inputs, facial_only=True):
    if (face, branch) in visited:
        return "cycle"
    if point[0] <= 0.0:
        return "symmetry_plane"
    if step > 8 and anchor_tree.query(point)[0] < inputs.diagonal / 120.0:
        return "anchor"
    if step > 3 and registry is not None and registry.query(point)[0] < inputs.diagonal / 180.0:
        return "trace"
    if facial_only and not face_is_facial(face, inputs):
        return "facial_boundary"
    return ""


def face_is_facial(face, inputs):
    center = inputs.vertices[inputs.faces[face]].mean(axis=0)
    normal = inputs.normals[inputs.faces[face]].mean(axis=0)
    return normal[1] < -0.1 and 0.05 < center[2] < 1.85 and abs(center[0]) < 1.0


def raised_paths(results, inputs, offset):
    lines = []
    for result in results:
        hits = [guide_test._nearest(inputs.bvh, point) for point in result.points]
        normals = guide_test._normalize(np.asarray([hit[1] for hit in hits]))
        lines.append((result.points + (normals * offset), False))
    return tuple(lines)


def singularity_markers(records, inputs):
    indices = np.asarray([record[0] for record in records], dtype=np.int32)
    return field_test.marker_lines(indices, inputs, 0.026, 0.02)


def unresolved_markers(results, inputs):
    points = [result.points[-1] for result in results if result.reason not in {"anchor", "trace"}]
    indices = nearest_indices(points, inputs)
    return field_test.marker_lines(indices, inputs, 0.018, 0.023)


def nearest_indices(points, inputs):
    from scipy.spatial import cKDTree
    if not points:
        return np.empty(0, dtype=np.int32)
    return cKDTree(inputs.vertices).query(np.asarray(points), workers=-1)[1].astype(np.int32)


def materials(skin):
    values = field_test.materials(skin)
    values["trace"] = guide_test.material("AF_SEPARATRIX_TRACE", (0.1, 1.0, 0.25), 2.5)
    values["pole"] = guide_test.material("AF_SEPARATRIX_POLE", (1.0, 0.72, 0.01), 3.5)
    values["unresolved"] = guide_test.material("AF_SEPARATRIX_UNRESOLVED", (1.0, 0.02, 0.72), 3.0)
    return values


def create_visuals(skin, anchors, guides, solution, records, results, inputs, collection):
    values, visuals = materials(skin), {"skin": skin}
    visuals["anchors"] = field_test.make_curve("AF_SEP_ANCHORS", field_test.raised_anchors(anchors, inputs), collection, values["anchor"], 0.0035)
    visuals["guides"] = field_test.make_curve("AF_SEP_GUIDES", guide_test.guide_lines(guides, inputs.bvh, 0.008), collection, values["guide"], 0.002)
    visuals["field"] = field_test.make_curve("AF_SEP_FIELD", field_test.field_lines(solution, inputs), collection, values["field"], 0.0011)
    visuals["traces"] = field_test.make_curve("AF_SEP_TRACES", raised_paths(results, inputs, 0.016), collection, values["trace"], 0.0022)
    visuals["poles"] = field_test.make_curve("AF_SEP_POLES", singularity_markers(records, inputs), collection, values["pole"], 0.0028)
    visuals["unresolved"] = field_test.make_curve("AF_SEP_UNRESOLVED", unresolved_markers(results, inputs), collection, values["unresolved"], 0.0024)
    return visuals


def render_variants():
    return {
        "field": {"skin", "anchors", "guides", "field"},
        "singularities": {"skin", "anchors", "poles"},
        "continuous_traces": {"skin", "anchors", "traces", "poles"},
        "trace_validation": {"skin", "anchors", "traces", "unresolved"},
    }


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
        field_test.set_visible(visuals, visible)
        guide_test._render_view(camera, (0.0, -8.0, 1.25), folder / f"{name}_front.png")
    render_threequarter(camera, visuals, variants, folder)
    contact_sheet(folder, tuple(variants))


def render_threequarter(camera, visuals, variants, folder):
    field_test.set_visible(visuals, variants["trace_validation"])
    guide_test._render_view(camera, (4.6, -7.0, 2.8), folder / "trace_validation_threequarter.png")


def contact_sheet(folder, names):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{name}_front.png").convert("RGB") for name in names]
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    labels = ("Anchor-constrained field", "Non-zero field indices",
              "Continuous triangle-domain traces", "Trace endpoints and failures")
    for index, (image, label) in enumerate(zip(images, labels)):
        field_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_separatrix_comparison.png")


def metrics_payload(records, results, seeds, inputs):
    reasons = {}
    for result in results:
        reasons[result.reason] = reasons.get(result.reason, 0) + 1
    return {
        "vertices": len(inputs.vertices), "triangles": len(inputs.faces),
        "singularities": len(records), "index_sum": int(sum(record[1] for record in records)),
        "half_domain_seeds": len(seeds), "symmetric_traces": len(results),
        "trace_points": int(sum(len(result.points) for result in results)),
        "termination_reasons": reasons,
    }


def save_outputs(args, metrics, visuals):
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    visuals["skin"]["af_topology_separatrix_test"] = json.dumps(metrics, sort_keys=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output), copy=True)


def trace_inputs(anchors, all_records, face_values, adjacency, inputs, facial_only=True):
    half_records = tuple(record for record in all_records if inputs.vertices[record[0], 0] >= 0.0)
    records = mirror_records(half_records, inputs)
    raw_seeds = anchor_seeds(anchors, inputs) + singularity_seeds(half_records, face_values, inputs)
    seeds = half_domain_seeds(raw_seeds, inputs)
    anchor_points = np.vstack([field_test.object_world_vertices(obj) for obj in anchors])
    traced = trace_all(seeds, face_values, adjacency, inputs, anchor_points, facial_only)
    results = symmetric_results(traced)
    return records, seeds, results


def build_prototype(args):
    root, skin = guide_test.scene_inputs()
    anchors, guides = field_test.anchor_objects(), field_test.open_guides(root)
    collection = guide_test.make_collection("AF_TOPOLOGY_SEPARATRIX_TEST")
    work = guide_test.duplicate_work_mesh(skin, args.target_faces, collection)
    inputs = field_test.field_inputs(work)
    rows = field_test.anchor_rows(anchors, inputs) + field_test.guide_rows(guides, anchors, inputs)
    solution = field_test.solve_field(inputs, rows)
    face_values = face_field(solution, inputs)
    all_records = singularities(solution, face_values, inputs, not args.full_surface)
    adjacency = face_adjacency(inputs.faces)
    records, seeds, results = trace_inputs(anchors, all_records, face_values, adjacency, inputs, not args.full_surface)
    return skin, anchors, guides, collection, inputs, solution, records, seeds, results


def finish_prototype(args, data):
    skin, anchors, guides, collection, inputs, solution, records, seeds, results = data
    metrics = metrics_payload(records, results, seeds, inputs)
    visuals = create_visuals(skin, anchors, guides, solution, records, results, inputs, collection)
    camera = prepare_render(visuals)
    render_all(camera, visuals, args.render_dir)
    save_outputs(args, metrics, visuals)
    print("AF_TOPOLOGY_SEPARATRIX_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
