import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_field as field_test
import prototype_topology_guides as guide_test
import prototype_topology_patches as patch_test
import prototype_topology_separatrix as trace_test


@dataclass(frozen=True)
class SegmentSoup:
    starts: np.ndarray
    ends: np.ndarray
    owners: np.ndarray


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=48000)
    parser.add_argument("--skip-render", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def selected_groups(groups, selected):
    return tuple(group for index, group in enumerate(groups) if selected[index])


def closed_segments(points):
    return points, np.roll(points, -1, axis=0)


def anchor_segments(anchors):
    pairs = [closed_segments(trace_test.outer_ring_points(anchor)) for anchor in anchors]
    starts = np.vstack([pair[0] for pair in pairs])
    ends = np.vstack([pair[1] for pair in pairs])
    return SegmentSoup(starts, ends, np.full(len(starts), -1, dtype=np.int32))


def layout_segments(groups, anchors):
    paths = physical_path_segments(groups)
    starts, ends, owners = [paths.starts], [paths.ends], [paths.owners]
    owner = int(paths.owners.max()) + 1
    for index, anchor in enumerate(anchors):
        for role, points in enumerate(trace_test.boundary_ring_points(anchor)):
            pair = closed_segments(points)
            starts.append(pair[0]); ends.append(pair[1])
            owners.append(np.full(len(pair[0]), owner + (2 * index) + role, dtype=np.int32))
    return SegmentSoup(np.vstack(starts), np.vstack(ends), np.concatenate(owners))


def physical_path_segments(groups):
    starts, ends, owners, owner = [], [], [], 0
    for group in groups:
        for result in group:
            starts.append(result.points[:-1]); ends.append(result.points[1:])
            owners.extend([owner] * (len(result.points) - 1)); owner += 1
    return SegmentSoup(np.vstack(starts), np.vstack(ends), np.asarray(owners, dtype=np.int32))


def layout_junctions(groups):
    values = [result.points[[0, -1]] for group in groups for result in group]
    return np.vstack(values)


def layout_scale(groups, anchors):
    values = [result.points for group in groups for result in group]
    values.extend(trace_test.outer_ring_points(anchor) for anchor in anchors)
    points = np.vstack(values)
    return float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))


def curve_edges(points, closed):
    return (points, np.roll(points, -1, axis=0)) if closed else (points[:-1], points[1:])


def junction_splits(points, closed, junctions, scale):
    starts, ends = curve_edges(points, closed)
    vectors = ends - starts
    factors = np.einsum("kij,ij->ki", junctions[:, None, :] - starts, vectors)
    factors /= np.maximum(np.einsum("ij,ij->i", vectors, vectors), 1.0e-12)
    projected = starts[None] + (np.clip(factors, 0.0, 1.0)[:, :, None] * vectors[None])
    distances = np.linalg.norm(projected - junctions[:, None], axis=2)
    splits = (np.argmin(distances, axis=1) + 1) % len(starts)
    return np.unique(splits[np.min(distances, axis=1) <= scale / 80.0])


def canonical_splits(points, closed, junctions, scale):
    splits = junction_splits(points, closed, junctions, scale)
    if closed and len(splits) < 2:
        splits = np.arange(0, len(points), max(1, len(points) // 4), dtype=np.int32)[:4]
    return np.unique(np.concatenate(([0], splits))).astype(np.int32)


def piece_owners(edge_count, splits, offset):
    labels = np.searchsorted(splits, np.arange(edge_count), side="right") - 1
    labels[labels < 0] = len(splits) - 1
    return labels + offset


def segmented_soup(records, junctions, scale):
    starts, ends, owners, offset = [], [], [], 0
    for points, closed in records:
        first, second = curve_edges(points, closed)
        splits = canonical_splits(points, closed, junctions, scale)
        starts.append(first); ends.append(second)
        owners.append(piece_owners(len(first), splits, offset))
        offset += len(splits)
    return SegmentSoup(np.vstack(starts), np.vstack(ends), np.concatenate(owners))


def path_segments(groups):
    starts, ends, owners = [], [], []
    for owner, group in enumerate(groups):
        for result in group:
            starts.append(result.points[:-1])
            ends.append(result.points[1:])
            owners.extend([owner] * (len(result.points) - 1))
    return SegmentSoup(np.vstack(starts), np.vstack(ends), np.asarray(owners, dtype=np.int32))


def closest_on_segments(point, soup, owner=None, limit=None):
    valid = np.ones(len(soup.starts), dtype=bool)
    if owner is not None:
        valid &= soup.owners != owner
    starts, ends = soup.starts[valid], soup.ends[valid]
    vectors = ends - starts
    factors = np.einsum("ij,ij->i", point - starts, vectors)
    factors /= np.maximum(np.einsum("ij,ij->i", vectors, vectors), 1.0e-12)
    projected = starts + (np.clip(factors, 0.0, 1.0)[:, None] * vectors)
    distances = np.linalg.norm(projected - point, axis=1)
    nearest = projected[np.argmin(distances)]
    return nearest if limit is None or distances.min() <= limit else point


def source_kind(source):
    return source.split(":", 1)[0]


def snapped_start(result, groups, group_index, anchors, limit):
    if source_kind(result.source) == "anchor":
        return closest_on_segments(result.points[0], anchors, limit=limit)
    return result.points[0]


def snapped_end(result, paths, anchors, group_index, limit):
    if result.reason == "anchor":
        return closest_on_segments(result.points[-1], anchors, limit=limit)
    if result.reason == "trace":
        return closest_on_segments(result.points[-1], paths, group_index, limit)
    return result.points[-1]


def project_point(point, inputs):
    return np.asarray(guide_test._nearest(inputs.bvh, point)[0])


def snap_result(result, groups, group_index, paths, anchors, inputs):
    points = result.points.copy()
    limit = inputs.diagonal / 80.0
    points[0] = project_point(snapped_start(result, groups, group_index, anchors, limit), inputs)
    points[-1] = project_point(snapped_end(result, paths, anchors, group_index, limit), inputs)
    return trace_test.TraceResult(points, result.reason, result.source)


def snap_pair(group, groups, index, paths, anchors, inputs):
    return tuple(snap_result(result, groups, index, paths, anchors, inputs) for result in group)


def snap_groups(groups, anchors, inputs):
    path_soup, anchor_soup = path_segments(groups), anchor_segments(anchors)
    return tuple(snap_pair(group, groups, index, path_soup, anchor_soup, inputs)
                 for index, group in enumerate(groups))


def project_result(result, inputs):
    points = np.asarray([project_point(point, inputs) for point in result.points])
    return trace_test.TraceResult(points, result.reason, result.source)


def project_groups(groups, inputs):
    return tuple(tuple(project_result(result, inputs) for result in group) for group in groups)


def snap_distances(before, after):
    values = []
    for old_group, new_group in zip(before, after):
        for old, new in zip(old_group, new_group):
            values.extend((np.linalg.norm(old.points[0] - new.points[0]),
                           np.linalg.norm(old.points[-1] - new.points[-1])))
    return np.asarray(values)


def snap_events(before, after):
    values = []
    for group_index, (old_group, new_group) in enumerate(zip(before, after)):
        for old, new in zip(old_group, new_group):
            values.extend(endpoint_events(group_index, old, new))
    return sorted(values, key=lambda item: -item["distance"])


def endpoint_events(group_index, old, new):
    labels = (("start", 0), ("end", -1))
    return [{"group": group_index, "endpoint": label, "source": old.source,
             "reason": old.reason, "distance": float(np.linalg.norm(old.points[index] - new.points[index]))}
            for label, index in labels]


def selected_partition(anchors, groups, adjacency, inputs):
    tree = patch_test.face_tree(inputs)
    anchor_mask = patch_test.anchor_barrier(anchors, tree, adjacency, len(inputs.faces))
    masks = patch_test.group_masks(groups, tree, adjacency, len(inputs.faces))
    pairs, areas = patch_test.face_pairs(adjacency), patch_test.triangle_areas(inputs)
    selected, partition = patch_test.select_groups(anchor_mask, masks, groups, pairs, areas, inputs)
    partition = patch_test.clean_tiny_islands(partition, pairs, areas, inputs)
    partition = repair_pinches(partition, pairs, areas, inputs)
    return selected, partition


def irregular_vertices(patch, inputs):
    triangles = inputs.faces[patch.faces]
    edges = np.sort(np.vstack((triangles[:, :2], triangles[:, 1:], triangles[:, (2, 0)])), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    vertices, degrees = np.unique(unique[counts == 1], return_counts=True)
    return vertices[degrees != 2]


def pinch_faces(partition, inputs):
    values = []
    for patch in partition.patches:
        if patch.kind == "invalid" and not patch.boundary_regular:
            bad = irregular_vertices(patch, inputs)
            values.extend(patch.faces[np.any(np.isin(inputs.faces[patch.faces], bad), axis=1)])
    return np.unique(values).astype(np.int32)


def repair_pinches(partition, pairs, areas, inputs):
    barrier = partition.barrier.copy()
    for _iteration in range(4):
        faces = pinch_faces(partition, inputs)
        if not len(faces):
            break
        barrier[faces] = True
        partition = patch_test.analyze_partition(barrier, pairs, areas, inputs)
        partition = patch_test.clean_tiny_islands(partition, pairs, areas, inputs)
    return partition


def materials(skin):
    values = trace_test.materials(skin)
    values["before"] = guide_test.material("AF_GRAPH_BEFORE", (1.0, 0.34, 0.03), 1.4)
    return values


def flattened(groups):
    return tuple(result for group in groups for result in group)


def create_visuals(skin, anchors, before, after, partition, inputs, collection):
    values = materials(skin)
    visuals = {"skin": skin}
    visuals["anchors"] = field_test.make_curve("AF_GRAPH_ANCHORS", field_test.raised_anchors(anchors, inputs), collection, values["anchor"], 0.0035)
    visuals["before"] = field_test.make_curve("AF_GRAPH_BEFORE", trace_test.raised_paths(flattened(before), inputs, 0.013), collection, values["before"], 0.0015)
    visuals["snapped"] = field_test.make_curve("AF_GRAPH_SNAPPED", trace_test.raised_paths(flattened(after), inputs, 0.017), collection, values["trace"], 0.0023)
    palette = patch_test.patch_materials()
    indices = patch_test.region_indices(partition, len(palette))
    visuals["regions"] = patch_test.colored_mesh("AF_GRAPH_REGIONS", inputs, collection, palette, indices)
    valid = patch_test.validity_materials()
    visuals["validity"] = patch_test.colored_mesh("AF_GRAPH_VALIDITY", inputs, collection, valid, patch_test.validity_indices(partition))
    return visuals


def render_specs():
    return (("before_front", {"skin", "anchors", "before"}, (0.0, -8.0, 1.25)),
            ("snapped_front", {"skin", "anchors", "snapped"}, (0.0, -8.0, 1.25)),
            ("regions_front", {"regions", "anchors", "snapped"}, (0.0, -8.0, 1.25)),
            ("validity_front", {"validity", "anchors", "snapped"}, (0.0, -8.0, 1.25)),
            ("regions_threequarter", {"regions", "anchors", "snapped"}, (4.6, -7.0, 2.8)),
            ("regions_back", {"regions", "snapped"}, (0.0, 8.0, 1.25)))


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
    labels = ("Selected paths before snapping", "Explicitly snapped path graph", "Snapped patch regions",
              "Green valid / magenta invalid", "Snapped regions - three-quarter", "Snapped regions - back")
    canvas = Image.new("RGB", (1440, 2160), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        patch_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_graph_comparison.png")


def patch_counts(partition):
    return {kind: sum(patch.kind == kind for patch in partition.patches)
            for kind in ("valid", "tiny", "invalid")}


def area_ratios(partition):
    values = {kind: sum(patch.area for patch in partition.patches if patch.kind == kind)
              for kind in ("valid", "tiny", "invalid")}
    total = max(sum(values.values()), 1.0e-12)
    return {kind: value / total for kind, value in values.items()}


def invalid_details(partition):
    total = max(sum(patch.area for patch in partition.patches), 1.0e-12)
    return [{"label": patch.label, "area_ratio": patch.area / total,
             "euler": patch.euler, "boundary_loops": patch.boundary_loops,
             "boundary_regular": patch.boundary_regular}
            for patch in partition.patches if patch.kind == "invalid"]


def boundary_edges(patch, inputs):
    triangles = inputs.faces[patch.faces]
    edges = np.sort(np.vstack((triangles[:, :2], triangles[:, 1:], triangles[:, (2, 0)])), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    return unique[counts == 1]


def nearest_owner(point, soup):
    vectors = soup.ends - soup.starts
    factors = np.einsum("ij,ij->i", point - soup.starts, vectors)
    factors /= np.maximum(np.einsum("ij,ij->i", vectors, vectors), 1.0e-12)
    projected = soup.starts + (np.clip(factors, 0.0, 1.0)[:, None] * vectors)
    return int(soup.owners[np.argmin(np.linalg.norm(projected - point, axis=1))])


def ordered_boundary(edges):
    neighbors = {}
    for first, second in edges:
        neighbors.setdefault(int(first), []).append(int(second))
        neighbors.setdefault(int(second), []).append(int(first))
    start, previous, current, output = int(edges[0, 0]), -1, int(edges[0, 0]), []
    for _index in range(len(edges)):
        following = [value for value in neighbors[current] if value != previous]
        following = start if start in following and len(output) == len(edges) - 1 else following[0]
        output.append((current, following))
        previous, current = current, following
    return np.asarray(output, dtype=np.int32)


def circular_runs(values):
    runs = []
    for value in values:
        if runs and runs[-1][0] == value:
            runs[-1][1] += 1
        else:
            runs.append([int(value), 1])
    if len(runs) > 1 and runs[0][0] == runs[-1][0]:
        runs[0][1] += runs.pop()[1]
    return runs


def stable_side_count(values):
    _owners, counts = np.unique(values, return_counts=True)
    threshold = max(3, int(np.ceil(len(values) * 0.02)))
    stable = int(np.count_nonzero(counts >= threshold))
    return stable or len(counts)


def patch_side_counts(partition, groups, anchors, inputs):
    soup = layout_segments(groups, anchors)
    values = []
    for patch in partition.patches:
        edges = ordered_boundary(boundary_edges(patch, inputs))
        centers = inputs.vertices[edges].mean(axis=1)
        owners = [nearest_owner(center, soup) for center in centers]
        values.append(stable_side_count(owners))
    return values


def metrics_payload(before, after, partition, distances, inputs, anchors):
    events = snap_events(before, after)
    sides = patch_side_counts(partition, after, anchors, inputs)
    return {"vertices": len(inputs.vertices), "triangles": len(inputs.faces),
            "selected_groups": len(after), "snapped_endpoints": int(np.count_nonzero(distances)),
            "mean_snap_distance": float(distances.mean()), "max_snap_distance": float(distances.max()),
            "patches": len(partition.patches), "patch_kinds": patch_counts(partition),
            "patch_area_ratios": area_ratios(partition),
            "patch_side_counts": sides, "max_patch_sides": max(sides),
            "invalid_patches": invalid_details(partition), "largest_snaps": events[:8]}


def save_outputs(args, metrics, visuals):
    folder = Path(args.render_dir)
    folder.mkdir(parents=True, exist_ok=True)
    Path(folder, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    visuals["skin"]["af_topology_graph_test"] = json.dumps(metrics, sort_keys=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output), copy=True)


def base_data(args):
    skin, anchors, collection, inputs, solution = patch_test.field_data(args)
    adjacency, results = patch_test.trace_data(anchors, inputs, solution)
    groups = project_groups(patch_test.trace_groups(results), inputs)
    return skin, anchors, collection, inputs, solution, adjacency, groups


def build_prototype(args):
    skin, anchors, collection, inputs, _solution, adjacency, candidates = base_data(args)
    snapped = snap_groups(candidates, anchors, inputs)
    selected, partition = selected_partition(anchors, snapped, adjacency, inputs)
    before, after = selected_groups(candidates, selected), selected_groups(snapped, selected)
    distances = snap_distances(before, after)
    return skin, anchors, collection, inputs, before, after, partition, distances


def finish_prototype(args, data):
    skin, anchors, collection, inputs, before, after, partition, distances = data
    metrics = metrics_payload(before, after, partition, distances, inputs, anchors)
    visuals = {"skin": skin}
    if not args.skip_render:
        visuals = create_visuals(skin, anchors, before, after, partition, inputs, collection)
        render_all(prepare_render(visuals), visuals, args.render_dir)
    save_outputs(args, metrics, visuals)
    print("AF_TOPOLOGY_GRAPH_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
