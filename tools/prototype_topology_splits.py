import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_field as field_test
import prototype_topology_graph as graph_test
import prototype_topology_guides as guide_test
import prototype_topology_mesh as mesh_test
import prototype_topology_patches as patch_test
import prototype_topology_separatrix as trace_test


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=48000)
    parser.add_argument("--skip-render", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def partition_inputs(anchors, groups, adjacency, inputs):
    tree = patch_test.face_tree(inputs)
    anchor = patch_test.anchor_barrier(anchors, tree, adjacency, len(inputs.faces))
    masks = patch_test.group_masks(groups, tree, adjacency, len(inputs.faces))
    pairs = patch_test.face_pairs(adjacency)
    areas = patch_test.triangle_areas(inputs)
    return anchor, masks, pairs, areas


def repaired_partition(barrier, pairs, areas, inputs):
    partition = patch_test.analyze_partition(barrier, pairs, areas, inputs)
    partition = patch_test.clean_tiny_islands(partition, pairs, areas, inputs)
    return graph_test.repair_pinches(partition, pairs, areas, inputs)


def initial_state(anchors, groups, adjacency, inputs):
    selected, partition = graph_test.selected_partition(anchors, groups, adjacency, inputs)
    anchor, masks, pairs, areas = partition_inputs(anchors, groups, adjacency, inputs)
    return selected, partition, anchor, masks, pairs, areas


def active_groups(groups, selected):
    return tuple(group for index, group in enumerate(groups) if selected[index])


def side_counts(partition, groups, anchors, inputs):
    return graph_test.patch_side_counts(partition, groups, anchors, inputs)


def side_score(counts):
    excess = sum(max(0, count - 6) for count in counts)
    return excess, max(counts), len(counts)


def valid_partition(partition):
    return all(patch.kind == "valid" for patch in partition.patches)


def candidate_trial(index, current, selected, masks, pairs, areas, inputs):
    barrier = current.barrier | masks[index]
    partition = repaired_partition(barrier, pairs, areas, inputs)
    trial_selected = selected.copy()
    trial_selected[index] = True
    return partition, trial_selected


def high_faces(partition, counts):
    values = [patch.faces for patch, count in zip(partition.patches, counts) if count > 6]
    return np.concatenate(values) if values else np.empty(0, dtype=np.int32)


def best_trial(current, counts, groups, selected, masks, pairs, areas, anchors, inputs):
    best = None
    targets = high_faces(current, counts)
    for index in np.flatnonzero(~selected):
        if np.count_nonzero(masks[index][targets]) < 3:
            continue
        partition, trial_selected = candidate_trial(index, current, selected, masks, pairs, areas, inputs)
        if not valid_partition(partition) or len(partition.patches) <= len(current.patches):
            continue
        trial_counts = side_counts(partition, active_groups(groups, trial_selected), anchors, inputs)
        score = side_score(trial_counts)
        if best is None or score < best[0]:
            best = score, int(index), (partition, trial_selected, trial_counts)
    return best


def repair_high_sides(current, groups, selected, masks, pairs, areas, anchors, inputs):
    counts = side_counts(current, active_groups(groups, selected), anchors, inputs)
    added = []
    for _iteration in range(8):
        if side_score(counts)[0] == 0:
            break
        best = best_trial(current, counts, groups, selected, masks, pairs, areas, anchors, inputs)
        if best is None or best[0] >= side_score(counts):
            break
        _score, index, (current, selected, counts) = best
        added.append(index)
    return current, selected, counts, tuple(added)


def remaining_high_patch(partition, counts):
    matches = [patch for patch, count in zip(partition.patches, counts) if count > 6]
    return matches[0] if len(matches) == 1 else None


def high_patches(partition, counts):
    return tuple(patch for patch, count in zip(partition.patches, counts) if count > 6)


def patch_edges(patch, inputs):
    triangles = inputs.faces[patch.faces]
    edges = np.vstack((triangles[:, :2], triangles[:, 1:], triangles[:, (2, 0)]))
    return np.unique(np.sort(edges, axis=1), axis=0)


def normalized(values):
    lengths = np.maximum(np.linalg.norm(values, axis=1), 1.0e-12)
    return values / lengths[:, None]


def field_alignment(edges, inputs, solution):
    vectors = normalized(inputs.vertices[edges[:, 1]] - inputs.vertices[edges[:, 0]])
    first = normalized(solution.directions[edges].mean(axis=1))
    normals = normalized(inputs.normals[edges].mean(axis=1))
    second = normalized(np.cross(normals, first))
    return np.maximum(np.abs(np.einsum("ij,ij->i", vectors, first)),
                      np.abs(np.einsum("ij,ij->i", vectors, second)))


def split_weights(edges, boundary, inputs, solution):
    vectors = inputs.vertices[edges[:, 1]] - inputs.vertices[edges[:, 0]]
    lengths = np.linalg.norm(vectors, axis=1)
    alignment = field_alignment(edges, inputs, solution)
    middle = inputs.vertices[edges].mean(axis=1)
    weights = lengths * (1.0 + 4.0 * np.square(1.0 - alignment))
    weights *= 1.0 + 4.0 * np.square(np.abs(middle[:, 0]) / (inputs.diagonal / 30.0))
    return weights * np.where(np.all(np.isin(edges, boundary), axis=1), 12.0, 1.0)


def side_corner_vertices(patch, groups, anchors, inputs):
    edges = graph_test.ordered_boundary(graph_test.boundary_edges(patch, inputs))
    centers = inputs.vertices[edges].mean(axis=1)
    soup = graph_test.layout_segments(groups, anchors)
    owners = np.asarray([graph_test.nearest_owner(point, soup) for point in centers])
    _values, counts = np.unique(owners, return_counts=True)
    stable = np.unique(owners)[counts >= max(3, int(np.ceil(len(owners) * 0.02)))]
    positions = np.flatnonzero(np.isin(owners, stable))
    changes = positions[owners[positions] != np.roll(owners[positions], 1)]
    return edges[changes, 0]


def diagonal_pairs(corners):
    count = len(corners)
    offsets = tuple({max(2, count // 2), min(count - 2, (count + 1) // 2)})
    pairs = {tuple(sorted((int(corners[i]), int(corners[(i + step) % count]))))
             for step in offsets for i in range(count)}
    return tuple(pairs)


def split_graph(patch, inputs, solution):
    boundary = np.unique(graph_test.boundary_edges(patch, inputs))
    edges = patch_edges(patch, inputs)
    weights = split_weights(edges, boundary, inputs, solution)
    return mesh_test._symmetric_graph(len(inputs.vertices), edges, weights, mesh_test._sparse_module())


def resample_path(points, count):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    samples = np.linspace(0.0, cumulative[-1], count)
    return np.column_stack([np.interp(samples, cumulative, points[:, axis]) for axis in range(3)])


def mirrored(points):
    values = points[::-1].copy()
    values[:, 0] *= -1.0
    return values


def symmetric_cross_path(points, inputs):
    oriented = points if points[0, 0] <= points[-1, 0] else points[::-1]
    endpoint_error = np.linalg.norm(oriented[0] - mirrored(oriented)[0])
    if endpoint_error > inputs.diagonal / 25.0:
        return points
    sampled = resample_path(oriented, max(32, len(points)))
    return 0.5 * (sampled + mirrored(sampled))


def is_self_mirrored(points, inputs):
    oriented = points if points[0, 0] <= points[-1, 0] else points[::-1]
    return np.linalg.norm(oriented[0] - mirrored(oriented)[0]) <= inputs.diagonal / 25.0


def mirrored_surface_path(points, inputs):
    values = points.copy(); values[:, 0] *= -1.0
    return np.asarray([graph_test.project_point(point, inputs) for point in values])


def split_group(graph, start, end, inputs):
    indices = mesh_test._shortest_path(graph, start, end, set())
    raw = inputs.vertices[indices]
    points = symmetric_cross_path(raw, inputs)
    result = trace_test.TraceResult(points, "patch_split", "generated:symmetric")
    if len(indices) <= 2 or is_self_mirrored(raw, inputs):
        return (result,) if len(indices) > 2 else ()
    reflected = trace_test.TraceResult(mirrored_surface_path(points, inputs), "patch_split", "generated:mirror")
    return result, reflected


def generated_candidates(patch, groups, anchors, inputs, solution):
    corners = side_corner_vertices(patch, groups, anchors, inputs)
    graph = split_graph(patch, inputs, solution)
    return tuple(group for pair in diagonal_pairs(corners)
                 if (group := split_group(graph, *pair, inputs)))


def generated_trial(current, group, groups, anchors, inputs, adjacency, pairs, areas):
    tree = patch_test.face_tree(inputs)
    barrier = current.barrier | patch_test.group_mask(group, tree, adjacency, len(inputs.faces))
    partition = repaired_partition(barrier, pairs, areas, inputs)
    final_groups = groups + (group,)
    counts = side_counts(partition, final_groups, anchors, inputs)
    return side_score(counts), partition, counts, final_groups, group


def best_generated(current, candidates, groups, anchors, inputs, adjacency, pairs, areas):
    trials = [generated_trial(current, group, groups, anchors, inputs, adjacency, pairs, areas)
              for group in candidates]
    valid = [trial for trial in trials if valid_partition(trial[1])]
    return min(valid, key=lambda trial: trial[0]) if valid else None


def report_generated(candidates, best, accepted):
    group = candidates[0] if candidates else ()
    partition, counts = (best[1], best[2]) if best else ((), ())
    payload = {"candidates": len(candidates), "first_points": len(group[0].points) if group else 0,
               "patches": len(partition.patches), "counts": counts,
               "valid": bool(best), "accepted": accepted}
    print("AF_GENERATED_SPLIT", json.dumps(payload), flush=True)


def all_generated_candidates(current, counts, groups, anchors, inputs, solution):
    values = [generated_candidates(patch, groups, anchors, inputs, solution)
              for patch in high_patches(current, counts)]
    return tuple(group for candidates in values for group in candidates)


def apply_generated_split(current, counts, groups, anchors, inputs, solution, adjacency, pairs, areas):
    added = []
    for _iteration in range(8):
        candidates = all_generated_candidates(current, counts, groups, anchors, inputs, solution)
        if not candidates:
            break
        best = best_generated(current, candidates, groups, anchors, inputs, adjacency, pairs, areas)
        accepted = bool(best and best[0] < side_score(counts))
        report_generated(candidates, best, accepted)
        if not accepted:
            break
        current, counts, groups = best[1], best[2], best[3]
        added.append(best[4])
    return current, counts, groups, tuple(added)


def fillability_materials():
    return [guide_test.material("AF_SPLIT_BARRIER", (0.015, 0.025, 0.05), 0.5),
            guide_test.material("AF_SPLIT_FILLABLE", (0.05, 0.75, 0.28), 0.8),
            guide_test.material("AF_SPLIT_HIGH_SIDED", (0.82, 0.02, 0.55), 1.2)]


def fillability_indices(partition, counts):
    indices = np.zeros(len(partition.labels), dtype=np.int32)
    for patch, count in zip(partition.patches, counts):
        indices[patch.faces] = 1 if count <= 6 else 2
    return indices


def materials(skin):
    values = trace_test.materials(skin)
    values["before"] = guide_test.material("AF_SPLIT_BEFORE", (1.0, 0.34, 0.03), 1.4)
    values["added"] = guide_test.material("AF_SPLIT_ADDED", (0.02, 0.85, 1.0), 2.0)
    return values


def group_results(groups):
    return tuple(result for group in groups for result in group)


def create_visuals(skin, anchors, before, added, final, partition, counts, inputs, collection):
    values, visuals = materials(skin), {"skin": skin}
    visuals["anchors"] = field_test.make_curve("AF_SPLIT_ANCHORS", field_test.raised_anchors(anchors, inputs), collection, values["anchor"], 0.0035)
    visuals["before"] = field_test.make_curve("AF_SPLIT_BEFORE", trace_test.raised_paths(group_results(before), inputs, 0.013), collection, values["before"], 0.0015)
    visuals["added"] = field_test.make_curve("AF_SPLIT_ADDED", trace_test.raised_paths(group_results(added), inputs, 0.018), collection, values["added"], 0.0026)
    visuals["final"] = field_test.make_curve("AF_SPLIT_FINAL", trace_test.raised_paths(group_results(final), inputs, 0.016), collection, values["trace"], 0.0018)
    palette = patch_test.patch_materials()
    visuals["regions"] = patch_test.colored_mesh("AF_SPLIT_REGIONS", inputs, collection, palette, patch_test.region_indices(partition, len(palette)))
    indices = fillability_indices(partition, counts)
    visuals["fillable"] = patch_test.colored_mesh("AF_SPLIT_FILLABILITY", inputs, collection, fillability_materials(), indices)
    return visuals


def render_specs():
    return (("before_front", {"skin", "anchors", "before"}, (0.0, -8.0, 1.25)),
            ("added_front", {"skin", "anchors", "before", "added"}, (0.0, -8.0, 1.25)),
            ("regions_front", {"regions", "anchors", "final"}, (0.0, -8.0, 1.25)),
            ("fillability_front", {"fillable", "anchors", "final"}, (0.0, -8.0, 1.25)),
            ("regions_threequarter", {"regions", "anchors", "final"}, (4.6, -7.0, 2.8)),
            ("regions_back", {"regions", "final"}, (0.0, 8.0, 1.25)))


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
    labels = ("Valid disks before side repair", "Inserted field-aligned diagonals", "Repaired patch regions",
              "Green: 2-6 sides / magenta: above 6", "Repaired regions - three-quarter", "Repaired regions - back")
    canvas = Image.new("RGB", (1440, 2160), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        patch_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_split_comparison.png")


def generated_symmetry_error(generated):
    if not generated:
        return 0.0
    errors = [result_symmetry_error(group) for group in generated]
    return float(max(errors))


def result_symmetry_error(group):
    if len(group) == 1:
        points = group[0].points
        return np.max(np.linalg.norm(points - mirrored(points), axis=1))
    first, second = group[0].points, group[1].points
    reflected = first.copy(); reflected[:, 0] *= -1.0
    from scipy.spatial import cKDTree
    return np.max(cKDTree(second).query(reflected)[0])


def metrics_payload(initial_counts, counts, selected, added, generated, partition, inputs):
    symmetry = generated_symmetry_error(generated)
    return {"vertices": len(inputs.vertices), "triangles": len(inputs.faces),
            "selected_groups": int(selected.sum()) + len(generated),
            "added_diagonal_groups": len(added) + len(generated),
            "added_group_indices": list(added), "patches": len(partition.patches),
            "generated_patch_splits": len(generated), "generated_symmetry_error": symmetry,
            "initial_side_counts": initial_counts, "final_side_counts": counts,
            "max_patch_sides": max(counts), "all_fillable": max(counts) <= 6,
            "all_disks": valid_partition(partition)}


def save_outputs(args, metrics, skin):
    folder = Path(args.render_dir)
    folder.mkdir(parents=True, exist_ok=True)
    Path(folder, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    skin["af_topology_split_test"] = json.dumps(metrics, sort_keys=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output), copy=True)


def build_prototype(args):
    skin, anchors, collection, inputs, solution, adjacency, candidates = graph_test.base_data(args)
    groups = graph_test.snap_groups(candidates, anchors, inputs)
    selected, initial, _anchor, masks, pairs, areas = initial_state(anchors, groups, adjacency, inputs)
    before = active_groups(groups, selected)
    initial_counts = side_counts(initial, before, anchors, inputs)
    result = repair_high_sides(initial, groups, selected, masks, pairs, areas, anchors, inputs)
    partition, selected, counts, added = result
    final = active_groups(groups, selected)
    partition, counts, final, generated = apply_generated_split(
        partition, counts, final, anchors, inputs, solution, adjacency, pairs, areas)
    base = (skin, anchors, collection, inputs, groups, before, initial_counts,
            partition, selected, counts, added, final, generated)
    return base + (solution, adjacency, pairs, areas)


def finish_prototype(args, data):
    core = data[:13]
    skin, anchors, collection, inputs, groups, before, initial_counts, partition, selected, counts, added, final, generated = core
    added_groups = tuple(groups[index] for index in added) + generated
    metrics = metrics_payload(initial_counts, counts, selected, added, generated, partition, inputs)
    if not args.skip_render:
        visuals = create_visuals(skin, anchors, before, added_groups, final, partition, counts, inputs, collection)
        render_all(prepare_render(visuals), visuals, args.render_dir)
    save_outputs(args, metrics, skin)
    print("AF_TOPOLOGY_SPLIT_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
