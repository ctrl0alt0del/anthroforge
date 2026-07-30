import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_annuli as annulus_test
import prototype_topology_graph as graph_test
import prototype_topology_guides as guide_test
import prototype_topology_splits as split_test
import prototype_topology_separatrix as trace_test


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--patchgen-exe", required=True)
    parser.add_argument("--glew-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=48000)
    parser.add_argument("--skip-render", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def stable_owner_values(values):
    _owners, counts = np.unique(values, return_counts=True)
    threshold = max(3, int(np.ceil(len(values) * 0.02)))
    stable = np.unique(values)[counts >= threshold]
    positions = np.flatnonzero(np.isin(values, stable))
    expanded = np.concatenate((positions - len(values), positions, positions + len(values)))
    from scipy.spatial import cKDTree
    nearest = cKDTree(expanded[:, None]).query(np.arange(len(values))[:, None])[1]
    return canonical_owner_values(values[expanded[nearest] % len(values)])


def owner_runs(values):
    starts = np.flatnonzero(values != np.roll(values, 1))
    return [(int(start), cyclic_range(start, starts[(i + 1) % len(starts)], len(values))[:-1])
            for i, start in enumerate(starts)]


def duplicate_run(values):
    runs = owner_runs(values)
    owners = [int(values[start]) for start, _indices in runs]
    repeated = {owner for owner in owners if owners.count(owner) > 1}
    choices = [(len(indices), start, indices) for start, indices in runs if int(values[start]) in repeated]
    return min(choices) if choices else None


def merge_run(values, record):
    _length, start, indices = record
    previous, following = values[(start - 1) % len(values)], values[(indices[-1] + 1) % len(values)]
    previous_size = np.count_nonzero(values == previous)
    following_size = np.count_nonzero(values == following)
    values[indices] = previous if previous_size >= following_size else following


def canonical_owner_values(values):
    result = values.copy()
    while len(owner_runs(result)) > len(np.unique(result)):
        record = duplicate_run(result)
        if record is None:
            break
        merge_run(result, record)
    return result


def cyclic_range(start, end, count):
    stop = end if end > start else end + count
    return np.arange(start, stop + 1, dtype=np.int32) % count


def owner_projection(point, soup, owner):
    keep = soup.owners == owner
    starts, vectors = soup.starts[keep], soup.ends[keep] - soup.starts[keep]
    factors = np.einsum("ij,ij->i", point - starts, vectors)
    factors /= np.maximum(np.einsum("ij,ij->i", vectors, vectors), 1.0e-12)
    projected = starts + (np.clip(factors, 0.0, 1.0)[:, None] * vectors)
    return projected[np.argmin(np.linalg.norm(projected - point, axis=1))]


def exact_layout_segments(groups, anchors):
    return graph_test.layout_segments(groups, anchors)


def projected_side(indices, edges, inputs, soup, owner):
    _soup, _owner = soup, owner
    return inputs.vertices[edges[indices, 0]].copy()


def close_patch_corners(polylines, inputs):
    values = [points.copy() for points in polylines]
    for index in range(len(values)):
        corner = 0.5 * (values[index - 1][-1] + values[index][0])
        corner = graph_test.project_point(corner, inputs)
        values[index - 1][-1], values[index][0] = corner, corner
    return tuple(values)


def patch_spec(patch, groups, anchors, inputs):
    edges = graph_test.ordered_boundary(graph_test.boundary_edges(patch, inputs))
    soup = exact_layout_segments(groups, anchors)
    centers = inputs.vertices[edges].mean(axis=1)
    owners = stable_owner_values(np.asarray([graph_test.nearest_owner(point, soup) for point in centers]))
    starts = np.flatnonzero(owners != np.roll(owners, 1))
    indices = [cyclic_range(start, starts[(i + 1) % len(starts)], len(edges)) for i, start in enumerate(starts)]
    lines = [projected_side(ids, edges, inputs, soup, int(owners[ids[0]])) for ids in indices]
    return {"patch": patch, "owners": tuple(map(int, owners[starts])),
            "polylines": close_patch_corners(lines, inputs),
            "boundary_vertices": edges[:, 0], "side_indices": tuple(indices)}


def patch_specs(partition, groups, anchors, inputs):
    specs = tuple(patch_spec(patch, groups, anchors, inputs) for patch in partition.patches)
    for spec in specs:
        expand_digon_spec(spec)
    return specs


def split_side(points, indices):
    middle = max(1, min(len(indices) - 2, len(indices) // 2))
    return (points[:middle + 1], points[middle:]), (indices[:middle + 1], indices[middle:])


def expand_digon_spec(spec):
    if len(spec["polylines"]) != 2:
        spec["synthetic_digon"] = False
        return
    values = [split_side(line, indices) for line, indices
              in zip(spec["polylines"], spec["side_indices"])]
    spec["polylines"] = tuple(line for value in values for line in value[0])
    spec["side_indices"] = tuple(side for value in values for side in value[1])
    spec["owners"] = tuple(owner for owner in spec["owners"] for _index in range(2))
    spec["synthetic_digon"] = True


def find_root(parents, index):
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def union_pair(parents, first, second):
    root_first, root_second = find_root(parents, first), find_root(parents, second)
    if root_first != root_second:
        parents[root_second] = root_first


def cluster_labels(points, tolerance):
    from scipy.spatial import cKDTree
    parents = np.arange(len(points), dtype=np.int32)
    for first, second in cKDTree(points).query_pairs(tolerance):
        union_pair(parents, first, second)
    roots = np.asarray([find_root(parents, index) for index in range(len(points))])
    return np.unique(roots, return_inverse=True)[1]


def cluster_centers(points, labels, inputs):
    values = [points[labels == label].mean(axis=0) for label in np.unique(labels)]
    return np.asarray([graph_test.project_point(point, inputs) for point in values])


def assign_corner_ids(specs, inputs):
    points = np.vstack([[line[0] for line in spec["polylines"]] for spec in specs])
    labels = cluster_labels(points, inputs.diagonal / 80.0)
    centers, offset = cluster_centers(points, labels, inputs), 0
    for spec in specs:
        count = len(spec["polylines"])
        spec["corners"] = tuple(map(int, labels[offset:offset + count]))
        offset += count
        apply_corner_centers(spec, centers)
        spec["corner_positions"] = centers[list(spec["corners"])]
    return centers


def apply_corner_centers(spec, centers):
    lines, corners = spec["polylines"], spec["corners"]
    for index, corner in enumerate(corners):
        lines[index - 1][-1] = centers[corner]
        lines[index][0] = centers[corner]


def side_records(specs):
    return [(si, pi, owner, points) for si, spec in enumerate(specs)
            for pi, (owner, points) in enumerate(zip(spec["owners"], spec["polylines"]))]


def endpoint_cost(first, second):
    direct = np.linalg.norm(first[0] - second[0]) + np.linalg.norm(first[-1] - second[-1])
    reverse = np.linalg.norm(first[0] - second[-1]) + np.linalg.norm(first[-1] - second[0])
    return min(direct, reverse)


def pairing_candidates(records):
    values = []
    for first in range(len(records)):
        for second in range(first + 1, len(records)):
            same_patch = records[first][0] == records[second][0]
            same_owner = records[first][2] == records[second][2]
            if same_patch or not same_owner:
                continue
            values.append((endpoint_cost(records[first][3], records[second][3]), first, second))
    return sorted(values)


def side_labels(records, tolerance):
    labels, next_label = np.full(len(records), -1, dtype=np.int32), 0
    for cost, first, second in pairing_candidates(records):
        if cost > tolerance or labels[first] >= 0 or labels[second] >= 0:
            continue
        labels[first] = labels[second] = next_label; next_label += 1
    for index in np.flatnonzero(labels < 0):
        labels[index] = next_label; next_label += 1
    return labels


def assign_side_ids(specs, inputs):
    records = side_records(specs)
    labels = side_labels(records, inputs.diagonal / 35.0)
    for record, label in zip(records, labels):
        specs[record[0]].setdefault("side_ids", [None] * len(specs[record[0]]["owners"]))
        specs[record[0]]["side_ids"][record[1]] = int(label)


def side_occurrences(specs):
    values = {}
    for spec in specs:
        for side_id, points in zip(spec["side_ids"], spec["polylines"]):
            values.setdefault(side_id, []).append(points)
    return values


def average_polyline(lines):
    count = max(32, max(len(line) for line in lines))
    sampled = [split_test.resample_path(line, count) for line in lines]
    return np.mean(sampled, axis=0)


def even_subdivisions(points, target):
    raw = max(2, int(round(np.linalg.norm(np.diff(points, axis=0), axis=1).sum() / target)))
    return raw if raw % 2 == 0 else raw + 1


def oriented_lines(lines):
    reference, values = lines[0], [lines[0]]
    for line in lines[1:]:
        direct = np.linalg.norm(reference[0] - line[0]) + np.linalg.norm(reference[-1] - line[-1])
        reverse = np.linalg.norm(reference[0] - line[-1]) + np.linalg.norm(reference[-1] - line[0])
        values.append(line if direct <= reverse else line[::-1])
    return values


def global_sides(specs, inputs):
    values, target = {}, inputs.diagonal / 58.0
    for key, lines in side_occurrences(specs).items():
        points = average_polyline(oriented_lines(lines))
        count = even_subdivisions(points, target)
        values[key] = split_test.resample_path(points, count + 1), count
    return values


def patch_side_keys(spec):
    return tuple(spec["side_ids"])


def patch_counts(spec, sides):
    return tuple(sides[key][1] for key in patch_side_keys(spec))


def patchgen_environment(glew_dir):
    values = os.environ.copy()
    values["PATH"] = str(glew_dir) + os.pathsep + values.get("PATH", "")
    return values


def stop_process(proc):
    proc.kill()
    proc.wait(timeout=2.0)


def complete_obj(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    if not lines or len(lines[0].split()) < 5:
        return False
    header = lines[0].split()
    vertices = sum(line.startswith("v ") for line in lines)
    faces = sum(line.startswith("f ") for line in lines)
    return vertices == int(header[1]) and faces == int(header[3])


def wait_for_patch(proc, folder, counts):
    for _iteration in range(1000):
        files = tuple(folder.glob("out_*.obj"))
        if files and complete_obj(files[0]):
            proc.terminate()
            proc.wait(timeout=2.0)
            return files[0]
        time.sleep(0.02)
    stop_process(proc)
    raise RuntimeError(f"patchgen did not produce an OBJ for {counts}")


def run_patchgen(counts, args):
    with tempfile.TemporaryDirectory(prefix="af_patchgen_") as folder_name:
        folder = Path(folder_name)
        proc = subprocess.Popen([args.patchgen_exe], cwd=folder, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=patchgen_environment(args.glew_dir), text=True)
        proc.stdin.write("0\n" + "\n".join(map(str, counts)) + "\n0\n")
        proc.stdin.flush()
        return parse_obj(wait_for_patch(proc, folder, counts))


def parse_obj(path):
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and parts[0] == "v":
            vertices.append(tuple(map(float, parts[1:4])))
        if parts and parts[0] == "f":
            faces.append(tuple(int(value.split("/")[0]) - 1 for value in parts[1:]))
    return np.asarray(vertices), np.asarray(faces, dtype=np.int32)


def boundary_loop(faces):
    pairs = [faces[:, (i, (i + 1) % faces.shape[1])] for i in range(faces.shape[1])]
    edges = np.sort(np.vstack(pairs), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    return graph_test.ordered_boundary(unique[counts == 1])[:, 0]


def regular_corners(count):
    if count == 2:
        return np.asarray(((-0.866025, 0.0), (0.866025, 0.0)))
    angles = (np.arange(count) * 2.0 * np.pi / count) - (0.5 * np.pi + np.pi / count)
    return np.column_stack((np.cos(angles), np.sin(angles)))


def rotate_loop(loop, position):
    return np.roll(loop, -int(position))


def patchgen_boundary(vertices, faces, counts):
    loop, corners = boundary_loop(faces), regular_corners(len(counts))
    start = np.argmin(np.linalg.norm(vertices[loop, :2] - corners[0], axis=1))
    forward, backward = rotate_loop(loop, start), rotate_loop(loop[::-1], len(loop) - 1 - start)
    first_error = np.linalg.norm(vertices[forward[counts[0]], :2] - corners[1])
    second_error = np.linalg.norm(vertices[backward[counts[0]], :2] - corners[1])
    return forward if first_error <= second_error else backward


def boundary_positions(spec, sides):
    values = []
    for index, key in enumerate(patch_side_keys(spec)):
        reference, points = spec["polylines"][index], sides[key][0]
        direct = np.linalg.norm(reference[0] - points[0]) + np.linalg.norm(reference[-1] - points[-1])
        reverse = np.linalg.norm(reference[0] - points[-1]) + np.linalg.norm(reference[-1] - points[0])
        points = (points if direct <= reverse else points[::-1]).copy()
        points[0] = spec["corner_positions"][index]
        points[-1] = spec["corner_positions"][(index + 1) % len(spec["polylines"])]
        values.append(points[:-1])
    return np.vstack(values)


def topology_edges(faces):
    pairs = [faces[:, (i, (i + 1) % faces.shape[1])] for i in range(faces.shape[1])]
    return np.unique(np.sort(np.vstack(pairs), axis=1), axis=0)


def harmonic_positions(vertices, faces, boundary, targets):
    from scipy import sparse
    from scipy.sparse.linalg import spsolve
    edges, count = topology_edges(faces), len(vertices)
    rows = np.concatenate((edges[:, 0], edges[:, 1]))
    cols = np.concatenate((edges[:, 1], edges[:, 0]))
    adjacency = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(count, count))
    laplacian = sparse.diags(np.asarray(adjacency.sum(axis=1)).ravel()) - adjacency
    interior = np.setdiff1d(np.arange(count), boundary)
    values = np.zeros((count, 3)); values[boundary] = targets
    values[interior] = spsolve(laplacian[interior][:, interior], -laplacian[interior][:, boundary] @ targets)
    return values, interior


def patch_bvh(patch, inputs):
    vertices = np.unique(inputs.faces[patch.faces])
    inverse = np.full(len(inputs.vertices), -1, dtype=np.int32)
    inverse[vertices] = np.arange(len(vertices), dtype=np.int32)
    faces = inverse[inputs.faces[patch.faces]]
    return guide_test.surface_bvh(inputs.vertices[vertices], faces)


def project_interior(vertices, interior, bvh):
    values = vertices.copy()
    for index in interior:
        values[index] = guide_test._nearest(bvh, values[index])[0]
    return values


def orient_quads(vertices, faces, bvh):
    centers = vertices[faces].mean(axis=1)
    normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                       vertices[faces[:, 3]] - vertices[faces[:, 0]])
    surface = np.asarray([guide_test._nearest(bvh, point)[1] for point in centers])
    return faces[:, ::-1] if np.mean(np.einsum("ij,ij->i", normals, surface)) < 0.0 else faces


def side_factors(points):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    return cumulative / max(cumulative[-1], 1.0e-12)


def source_boundary_data(spec):
    corners, vertex_ids, positions = regular_corners(len(spec["polylines"])), [], []
    for index, (line, indices) in enumerate(zip(spec["polylines"], spec["side_indices"])):
        factors = side_factors(line)[:-1]
        start, end = corners[index], corners[(index + 1) % len(corners)]
        positions.append(start + (factors[:, None] * (end - start)))
        vertex_ids.append(spec["boundary_vertices"][indices[:-1]])
    return np.concatenate(vertex_ids), np.vstack(positions)


def source_patch_arrays(spec, inputs):
    global_vertices = np.unique(inputs.faces[spec["patch"].faces])
    inverse = np.full(len(inputs.vertices), -1, dtype=np.int32)
    inverse[global_vertices] = np.arange(len(global_vertices), dtype=np.int32)
    faces = inverse[inputs.faces[spec["patch"].faces]]
    return global_vertices, inputs.vertices[global_vertices], faces, inverse


def source_parameterization(spec, inputs):
    global_vertices, vertices, faces, inverse = source_patch_arrays(spec, inputs)
    boundary, positions = source_boundary_data(spec)
    boundary = inverse[boundary]
    targets = np.column_stack((positions, np.zeros(len(positions))))
    uv, _interior = harmonic_positions(vertices, faces, boundary, targets)
    return vertices, faces, uv, global_vertices


def barycentric_coordinates(point, triangle):
    matrix = np.column_stack((triangle[1] - triangle[0], triangle[2] - triangle[0]))
    values = np.linalg.lstsq(matrix, point - triangle[0], rcond=None)[0]
    weights = np.asarray((1.0 - values.sum(), values[0], values[1]))
    weights = np.clip(weights, 0.0, 1.0)
    return weights / max(weights.sum(), 1.0e-12)


def surface_positions(points, source_vertices, source_faces, source_uv):
    bvh = guide_test.surface_bvh(source_uv, source_faces)
    values = []
    for point in points:
        hit = guide_test._nearest(bvh, (point[0], point[1], 0.0))
        triangle = source_faces[hit[2]]
        weights = barycentric_coordinates(np.asarray(hit[0]), source_uv[triangle])
        values.append(weights @ source_vertices[triangle])
    return np.asarray(values)


def local_boundary_positions(spec, counts):
    values = [split_test.resample_path(line, count + 1)[:-1]
              for line, count in zip(spec["polylines"], counts)]
    return np.vstack(values)


def polygon_boundary_positions(counts):
    corners, values = regular_corners(len(counts)), []
    for index, count in enumerate(counts):
        factors = np.linspace(0.0, 1.0, count, endpoint=False)
        start, end = corners[index], corners[(index + 1) % len(corners)]
        values.append(start + (factors[:, None] * (end - start)))
    return np.vstack(values)


def template_parameterization(vertices, faces, counts):
    boundary = patchgen_boundary(vertices, faces, counts)
    positions = polygon_boundary_positions(counts)
    targets = np.column_stack((positions, np.zeros(len(positions))))
    mapped, _interior = harmonic_positions(vertices, faces, boundary, targets)
    return mapped, boundary


def build_patch_mesh(spec, sides, topology, inputs):
    template_vertices, faces = topology
    counts = patch_counts(spec, sides)
    template_uv, boundary = template_parameterization(template_vertices, faces, counts)
    source_vertices, source_faces, source_uv, _global = source_parameterization(spec, inputs)
    vertices = surface_positions(template_uv, source_vertices, source_faces, source_uv)
    vertices[boundary] = local_boundary_positions(spec, counts)
    bvh = patch_bvh(spec["patch"], inputs)
    return vertices, orient_quads(vertices, faces, bvh)


def face_edges(vertices, faces):
    pairs = [faces[:, (index, (index + 1) % 4)] for index in range(4)]
    indices = np.vstack(pairs)
    return np.linalg.norm(vertices[indices[:, 0]] - vertices[indices[:, 1]], axis=1)


def face_edge_indices(faces):
    return np.vstack([faces[:, (index, (index + 1) % 4)] for index in range(4)])


def face_surface_errors(vertices, faces, bvh):
    centers = vertices[faces].mean(axis=1)
    nearest = np.asarray([guide_test._nearest(bvh, point)[0] for point in centers])
    return np.linalg.norm(nearest - centers, axis=1)


def boundary_diagnostics(spec, part, topology, sides, diagonal):
    source_vertices, source_faces = topology
    boundary = patchgen_boundary(source_vertices, source_faces, patch_counts(spec, sides))
    targets = boundary_positions(spec, sides)
    steps = np.linalg.norm(np.roll(targets, -1, axis=0) - targets, axis=1)
    pairs, lengths = face_edge_indices(part[1]), face_edges(*part)
    longest = pairs[int(np.argmax(lengths))]
    return {"boundary_min_step": float(steps.min()), "boundary_max_step": float(steps.max()),
            "longest_edge_boundary_vertices": int(np.isin(longest, boundary).sum()),
            "zero_edges": int(np.count_nonzero(lengths <= diagonal * 1.0e-9))}


def patch_diagnostics(spec, part, topology, sides, inputs):
    vertices, faces = part
    lengths = face_edges(vertices, faces)
    bvh = patch_bvh(spec["patch"], inputs)
    errors = face_surface_errors(vertices, faces, bvh)
    finite = bool(np.isfinite(vertices).all())
    ratio = float(lengths.max() / max(lengths.min(), 1.0e-12))
    valid = finite and lengths.max() <= inputs.diagonal / 12.0
    valid &= ratio <= 40.0 and errors.max() <= inputs.diagonal / 30.0
    report = {"valid": bool(valid), "max_edge": float(lengths.max()),
              "edge_ratio": ratio, "max_surface_error": float(errors.max()),
              "counts": patch_counts(spec, sides), "label": int(spec["patch"].label),
              "synthetic_digon": bool(spec["synthetic_digon"])}
    report.update(boundary_diagnostics(spec, part, topology, sides, inputs.diagonal))
    return report


def build_patch_parts(specs, sides, cache, inputs):
    parts, reports = [], []
    for spec in specs:
        topology = cache[patch_counts(spec, sides)]
        part = build_patch_mesh(spec, sides, topology, inputs)
        report = patch_diagnostics(spec, part, topology, sides, inputs)
        parts.append(part if report["valid"] else None)
        reports.append(report)
    return tuple(parts), tuple(reports)


def accepted_parts(parts):
    return tuple(part for part in parts if part is not None)


def quad_state(partition, groups, anchors, inputs, args):
    specs = patch_specs(partition, groups, anchors, inputs)
    assign_corner_ids(specs, inputs)
    assign_side_ids(specs, inputs)
    sides = global_sides(specs, inputs)
    cache = topology_cache(specs, sides, args)
    parts, reports = build_patch_parts(specs, sides, cache, inputs)
    return specs, sides, parts, reports


def rejected_patches(partition, reports):
    return tuple(patch for patch, report in zip(partition.patches, reports)
                 if not report["valid"] and not report["synthetic_digon"])


def rejected_face_mask(partition, reports, face_count):
    mask = np.zeros(face_count, dtype=bool)
    for patch in rejected_patches(partition, reports):
        mask[patch.faces] = True
    return mask


def quality_candidates(partition, reports, groups, anchors, inputs, solution):
    patches = rejected_patches(partition, reports)
    values = [split_test.generated_candidates(patch, groups, anchors, inputs, solution)
              for patch in patches]
    return tuple(group for candidates in values for group in candidates)


def trial_overlap_score(trial, target):
    overlaps = [int(np.count_nonzero(target[patch.faces])) for patch in trial[1].patches]
    active = [value for value in overlaps if value]
    return max(active), sum(value * value for value in active), len(active)


def quality_trials(current, candidates, groups, anchors, inputs, adjacency, pairs, areas, target):
    values = [split_test.generated_trial(current, group, groups, anchors, inputs,
                                         adjacency, pairs, areas) for group in candidates]
    valid = [trial for trial in values if split_test.valid_partition(trial[1])
             and max(trial[2]) <= 6]
    return sorted(valid, key=lambda trial: trial_overlap_score(trial, target))


def rejection_score(partition, reports):
    sizes = [len(patch.faces) for patch, report in zip(partition.patches, reports)
             if not report["valid"]]
    return sum(sizes), max(sizes, default=0), len(sizes)


def try_quality_trials(trials, current_score, anchors, inputs, args):
    for trial in trials[:4]:
        state = quad_state(trial[1], trial[3], anchors, inputs, args)
        if rejection_score(trial[1], state[3]) < current_score:
            return trial[1], trial[3], state, trial[4]
    return None


def refine_quality(partition, groups, state, anchors, inputs, solution, adjacency, pairs, areas, args):
    added = []
    for _iteration in range(4):
        target = rejected_face_mask(partition, state[3], len(inputs.faces))
        candidates = quality_candidates(partition, state[3], groups, anchors, inputs, solution)
        trials = quality_trials(partition, candidates, groups, anchors, inputs, adjacency, pairs, areas, target)
        improved = try_quality_trials(trials, rejection_score(partition, state[3]), anchors, inputs, args)
        if improved is None:
            break
        partition, groups, state, group = improved
        added.append(group)
        print("AF_QUALITY_SPLIT", rejection_score(partition, state[3]), flush=True)
    return partition, groups, state, tuple(added)


def topology_cache(specs, sides, args):
    values = {}
    for spec in specs:
        counts = patch_counts(spec, sides)
        print("AF_PATCH_SIGNATURE", counts, flush=True)
        if counts not in values:
            values[counts] = run_patchgen(counts, args)
    return values


def combine_parts(parts):
    vertices, faces, offset = [], [], 0
    for part_vertices, part_faces in parts:
        vertices.append(part_vertices)
        faces.append(part_faces + offset)
        offset += len(part_vertices)
    return np.vstack(vertices), np.vstack(faces)


def weld_mesh(vertices, faces, tolerance):
    keys = np.round(vertices / tolerance).astype(np.int64)
    _unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    welded, remapped = vertices[first], inverse[faces]
    keep = np.asarray([len(set(map(int, face))) == 4 for face in remapped])
    return welded, remapped[keep]


def edge_incidence(faces):
    pairs = [faces[:, (i, (i + 1) % 4)] for i in range(4)]
    edges = np.sort(np.vstack(pairs), axis=1)
    _unique, counts = np.unique(edges, axis=0, return_counts=True)
    return counts


def create_mesh_object(vertices, faces, collection):
    mesh = bpy.data.meshes.new("AF_TOPO_QUAD_PATCHES_MESH")
    mesh.from_pydata(vertices.tolist(), [], faces.tolist())
    obj = bpy.data.objects.new("AF_TOPO_QUAD_PATCHES", mesh)
    collection.objects.link(obj)
    obj["af_topology_quad_test"] = True
    return obj


def rejected_face_indices(partition, reports):
    values = [patch.faces for patch, report in zip(partition.patches, reports) if not report["valid"]]
    return np.concatenate(values) if values else np.empty(0, dtype=np.int32)


def create_rejected_object(partition, reports, inputs, collection):
    indices = rejected_face_indices(partition, reports)
    faces = inputs.faces[indices]
    mesh = bpy.data.meshes.new("AF_TOPO_REJECTED_PATCHES_MESH")
    mesh.from_pydata(split_test.patch_test.offset_vertices(inputs).tolist(), [], faces.tolist())
    obj = bpy.data.objects.new("AF_TOPO_REJECTED_PATCHES", mesh)
    collection.objects.link(obj)
    obj.data.materials.append(guide_test.material("AF_TOPO_REJECTED", (0.95, 0.01, 0.22), 1.5))
    return obj


def copy_annuli(anchors, collection, material):
    values = []
    for anchor in anchors:
        obj = anchor.copy(); obj.data = anchor.data.copy()
        collection.objects.link(obj); obj.data.materials.clear(); obj.data.materials.append(material)
        values.append(obj)
    return tuple(values)


def visual_objects(skin, quad, rejected, anchors, collection):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_QUAD_SKIN", (0.12, 0.16, 0.21)))
    quad.data.materials.append(guide_test.material("AF_QUAD_PATCH", (0.025, 0.08, 0.12)))
    wire = annulus_test.make_wire_object(quad, collection, guide_test.material("AF_QUAD_WIRE", (0.03, 0.9, 1.0), 1.8))
    annuli = copy_annuli(anchors, collection, guide_test.material("AF_QUAD_ANNULUS", (0.85, 0.04, 0.025), 1.3))
    annulus_wires = annulus_test.make_wire_objects(annuli, collection, guide_test.material("AF_QUAD_LOOP_WIRE", (1.0, 0.7, 0.05), 2.2))
    return {"skin": skin, "quad": quad, "wire": wire, "rejected": rejected,
            "annuli": annuli, "annulus_wires": annulus_wires}


def render_specs():
    front = (0.0, -8.0, 1.25)
    quarter = (4.6, -7.0, 2.8)
    return (("wire_front", {"skin", "wire", "rejected", "annulus_wires"}, front),
            ("surface_front", {"quad", "wire", "rejected", "annulus_wires"}, front),
            ("loops_front", {"skin", "wire", "rejected", "annuli", "annulus_wires"}, front),
            ("surface_threequarter", {"quad", "wire", "rejected", "annulus_wires"}, quarter),
            ("wire_threequarter", {"skin", "wire", "rejected", "annulus_wires"}, quarter),
            ("surface_back", {"quad", "wire", "rejected"}, (0.0, 8.0, 1.25)))


def visible_objects(visuals, names):
    values = []
    for name in names:
        item = visuals[name]
        values.extend(item if isinstance(item, tuple) else (item,))
    return set(values)


def render_all(visuals, folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    guide_test._render_settings(); camera = guide_test._camera(); guide_test._lights()
    for name, visible, position in render_specs():
        allowed = visible_objects(visuals, visible)
        for obj in tuple(bpy.context.scene.objects):
            obj.hide_render = obj not in allowed
        guide_test._render_view(camera, position, folder / f"{name}.png")
    contact_sheet(folder)


def contact_sheet(folder):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{item[0]}.png").convert("RGB") for item in render_specs()]
    labels = ("Quad wires on skin", "Generated quad patch surfaces", "Preserved annulus bands",
              "Quad surfaces - three-quarter", "Quad wires - three-quarter", "Quad surfaces - back")
    canvas = Image.new("RGB", (1440, 2160), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        split_test.patch_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_quad_comparison.png")


def metrics_payload(vertices, faces, specs, sides, counts, reports):
    incidence = edge_incidence(faces)
    rejected = [report for report in reports if not report["valid"]]
    return {"vertices": len(vertices), "quads": len(faces), "patches": len(specs),
            "shared_sides": len(sides), "patch_side_counts": counts,
            "all_quads": bool(faces.shape[1] == 4), "boundary_edges": int(np.count_nonzero(incidence == 1)),
            "nonmanifold_edges": int(np.count_nonzero(incidence > 2)),
            "max_patch_sides": max(map(len, counts)), "annulus_bands_reserved": True,
            "accepted_patches": len(reports) - len(rejected), "rejected_patches": rejected}


def build_prototype(args):
    data = split_test.build_prototype(args)
    skin, anchors, collection, inputs = data[:4]
    partition, final = data[7], data[11]
    solution, adjacency, pairs, areas = data[13:]
    initial = quad_state(partition, final, anchors, inputs, args)
    refined = refine_quality(partition, final, initial, anchors, inputs, solution,
                             adjacency, pairs, areas, args)
    partition, final, state, quality_added = refined
    specs, sides, parts, reports = state
    vertices, faces = weld_mesh(*combine_parts(accepted_parts(parts)), inputs.diagonal * 1.0e-8)
    counts = [patch_counts(spec, sides) for spec in specs]
    print("AF_QUALITY_SPLITS_ACCEPTED", len(quality_added), flush=True)
    return skin, anchors, collection, inputs, partition, vertices, faces, specs, sides, counts, reports


def finish_prototype(args, data):
    skin, anchors, collection, inputs, partition, vertices, faces, specs, sides, counts, reports = data
    quad = create_mesh_object(vertices, faces, collection)
    rejected = create_rejected_object(partition, reports, inputs, collection)
    metrics = metrics_payload(vertices, faces, specs, sides, counts, reports)
    visuals = visual_objects(skin, quad, rejected, anchors, collection)
    if not args.skip_render:
        render_all(visuals, args.render_dir)
    Path(args.render_dir).mkdir(parents=True, exist_ok=True)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    quad["af_topology_quad_stats"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)
    print("AF_TOPOLOGY_QUAD_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
