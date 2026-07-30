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
import prototype_topology_separatrix as trace_test


@dataclass(frozen=True)
class PatchInfo:
    label: int
    faces: np.ndarray
    area: float
    euler: int
    boundary_loops: int
    boundary_regular: bool
    kind: str


@dataclass(frozen=True)
class Partition:
    labels: np.ndarray
    barrier: np.ndarray
    patches: tuple
    score: float


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=48000)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def triangle_areas(inputs):
    triangles = inputs.vertices[inputs.faces]
    crosses = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    return np.linalg.norm(crosses, axis=1) * 0.5


def face_pairs(adjacency):
    rows = np.repeat(np.arange(len(adjacency[0]), dtype=np.int32), 3)
    columns = adjacency[0].reshape(-1)
    keep = (columns >= 0) & (rows < columns)
    return rows[keep], columns[keep]


def trace_groups(results):
    groups, index = [], 0
    while index < len(results):
        width = pair_width(results, index)
        groups.append(tuple(results[index : index + width]))
        index += width
    return tuple(groups)


def pair_width(results, index):
    if index + 1 >= len(results):
        return 1
    expected = f"{results[index].source}:mirror"
    return 2 if results[index + 1].source == expected else 1


def curve_face_ids(points, tree):
    if len(points) < 2:
        return np.asarray(tree.query(points)[1], dtype=np.int32)
    samples = np.vstack((points, (points[:-1] + points[1:]) * 0.5))
    return np.unique(np.asarray(tree.query(samples)[1], dtype=np.int32))


def dilated_faces(indices, adjacency, rings=1):
    values = np.unique(np.asarray(indices, dtype=np.int32))
    for _ring in range(rings):
        neighbors = adjacency[0][values].reshape(-1)
        values = np.unique(np.concatenate((values, neighbors[neighbors >= 0])))
    return values


def face_tree(inputs):
    from scipy.spatial import cKDTree
    return cKDTree(inputs.vertices[inputs.faces].mean(axis=1))


def anchor_barrier(anchors, tree, adjacency, face_count):
    barrier = np.zeros(face_count, dtype=bool)
    for anchor in anchors:
        for points in trace_test.ring_point_sets(anchor):
            ids = curve_face_ids(points, tree)
            barrier[dilated_faces(ids, adjacency)] = True
    return barrier


def group_mask(group, tree, adjacency, face_count):
    mask = np.zeros(face_count, dtype=bool)
    for result in group:
        ids = curve_face_ids(result.points, tree)
        mask[dilated_faces(ids, adjacency)] = True
    return mask


def group_masks(groups, tree, adjacency, face_count):
    return np.asarray([group_mask(group, tree, adjacency, face_count) for group in groups])


def active_labels(barrier, pairs, face_count):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    active = np.flatnonzero(~barrier)
    inverse = np.full(face_count, -1, dtype=np.int32)
    inverse[active] = np.arange(len(active), dtype=np.int32)
    keep = (~barrier[pairs[0]]) & (~barrier[pairs[1]])
    rows, columns = inverse[pairs[0][keep]], inverse[pairs[1][keep]]
    graph = symmetric_graph(rows, columns, len(active), coo_matrix)
    _count, labels = connected_components(graph, directed=False)
    return active, labels


def symmetric_graph(rows, columns, count, matrix_type):
    diagonal = np.arange(count, dtype=np.int32)
    first = np.concatenate((rows, columns, diagonal))
    second = np.concatenate((columns, rows, diagonal))
    return matrix_type((np.ones(len(first)), (first, second)), shape=(count, count))


def boundary_components(edges):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    vertices = np.unique(edges)
    inverse = {int(value): index for index, value in enumerate(vertices)}
    rows = np.asarray([inverse[int(value)] for value in edges[:, 0]], dtype=np.int32)
    columns = np.asarray([inverse[int(value)] for value in edges[:, 1]], dtype=np.int32)
    graph = symmetric_graph(rows, columns, len(vertices), coo_matrix)
    return int(connected_components(graph, directed=False)[0])


def patch_topology(face_ids, inputs):
    triangles = inputs.faces[face_ids]
    edges = np.sort(np.vstack((triangles[:, :2], triangles[:, 1:], triangles[:, (2, 0)])), axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = unique_edges[counts == 1]
    vertices, degrees = np.unique(boundary, return_counts=True)
    regular = bool(len(boundary) and np.all(degrees == 2))
    loops = boundary_components(boundary) if len(boundary) else 0
    euler = len(np.unique(triangles)) - len(unique_edges) + len(triangles)
    return int(euler), loops, regular


def patch_kind(area, total_area, euler, loops, regular):
    if area < total_area / 1200.0:
        return "tiny"
    if euler == 1 and loops == 1 and regular:
        return "valid"
    return "invalid"


def patch_info(label, face_ids, areas, total_area, inputs):
    area = float(areas[face_ids].sum())
    euler, loops, regular = patch_topology(face_ids, inputs)
    kind = patch_kind(area, total_area, euler, loops, regular)
    return PatchInfo(label, face_ids, area, euler, loops, regular, kind)


def partition_score(patches, total_area):
    invalid = sum(patch.area for patch in patches if patch.kind == "invalid")
    tiny = sum(patch.area for patch in patches if patch.kind == "tiny")
    return (1000.0 * invalid / total_area) + (250.0 * tiny / total_area) + (0.04 * len(patches))


def analyze_partition(barrier, pairs, areas, inputs):
    active, labels = active_labels(barrier, pairs, len(inputs.faces))
    total_area = float(areas.sum())
    values = [patch_info(label, active[labels == label], areas, total_area, inputs)
              for label in range(int(labels.max()) + 1)]
    full_labels = np.full(len(inputs.faces), -1, dtype=np.int32)
    full_labels[active] = labels
    return Partition(full_labels, barrier.copy(), tuple(values), partition_score(values, total_area))


def clean_tiny_islands(partition, pairs, areas, inputs):
    barrier = partition.barrier.copy()
    for _iteration in range(4):
        tiny = [patch.faces for patch in partition.patches if patch.kind == "tiny"]
        if not tiny:
            break
        barrier[np.concatenate(tiny)] = True
        partition = analyze_partition(barrier, pairs, areas, inputs)
    return partition


def initial_coverage(anchor_mask, masks):
    coverage = masks.sum(axis=0, dtype=np.int32)
    coverage[anchor_mask] += len(masks) + 1
    return coverage


def removal_order(groups):
    lengths = [sum(path_length(result.points) for result in group) for group in groups]
    return np.argsort(lengths).astype(np.int32)


def path_length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def select_groups(anchor_mask, masks, groups, pairs, areas, inputs):
    selected = np.ones(len(groups), dtype=bool)
    coverage = initial_coverage(anchor_mask, masks)
    current = analyze_partition(coverage > 0, pairs, areas, inputs)
    for index in removal_order(groups):
        current, removed = removal_trial(index, masks, coverage, current, pairs, areas, inputs)
        if removed:
            selected[index] = False
    return selected, current


def removal_trial(index, masks, coverage, current, pairs, areas, inputs):
    trial_coverage = coverage - masks[index]
    trial = analyze_partition(trial_coverage > 0, pairs, areas, inputs)
    if trial.score > current.score + 0.02:
        return current, False
    coverage[:] = trial_coverage
    return trial, True


def flatten_groups(groups, selected, keep):
    output = []
    for index, group in enumerate(groups):
        if bool(selected[index]) == keep:
            output.extend(group)
    return tuple(output)


def patch_materials():
    colors = ((0.10, 0.18, 0.32), (0.10, 0.52, 0.70), (0.18, 0.72, 0.48),
              (0.65, 0.72, 0.18), (0.86, 0.50, 0.12), (0.76, 0.22, 0.45),
              (0.48, 0.28, 0.78), (0.18, 0.64, 0.68))
    barrier = guide_test.material("AF_PATCH_BARRIER", (0.015, 0.025, 0.05), 0.5)
    patches = [guide_test.material(f"AF_PATCH_{index}", color, 0.8) for index, color in enumerate(colors)]
    return [barrier] + patches


def validity_materials():
    return [guide_test.material("AF_BARRIER", (0.015, 0.025, 0.05), 0.5),
            guide_test.material("AF_VALID_DISK", (0.05, 0.75, 0.28), 0.8),
            guide_test.material("AF_TINY_PATCH", (1.0, 0.24, 0.02), 1.2),
            guide_test.material("AF_INVALID_PATCH", (0.82, 0.02, 0.55), 1.2)]


def offset_vertices(inputs):
    return inputs.vertices + (inputs.normals * inputs.diagonal / 3500.0)


def colored_mesh(name, inputs, collection, materials, indices):
    mesh = bpy.data.meshes.new(f"{name}_MESH")
    mesh.from_pydata(offset_vertices(inputs).tolist(), [], inputs.faces.tolist())
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    for material in materials:
        mesh.materials.append(material)
    for polygon, index in zip(mesh.polygons, indices):
        polygon.material_index = int(index)
    return obj


def region_indices(partition, material_count):
    indices = np.zeros(len(partition.labels), dtype=np.int32)
    active = partition.labels >= 0
    indices[active] = 1 + (partition.labels[active] % (material_count - 1))
    return indices


def validity_indices(partition):
    indices = np.zeros(len(partition.labels), dtype=np.int32)
    mapping = {"valid": 1, "tiny": 2, "invalid": 3}
    for patch in partition.patches:
        indices[patch.faces] = mapping[patch.kind]
    return indices


def create_visuals(skin, anchors, groups, selected, partition, inputs, collection):
    materials = trace_test.materials(skin)
    selected_paths = flatten_groups(groups, selected, True)
    rejected_paths = flatten_groups(groups, selected, False)
    visuals = {"skin": skin}
    visuals["anchors"] = field_test.make_curve("AF_PATCH_ANCHORS", field_test.raised_anchors(anchors, inputs), collection, materials["anchor"], 0.0035)
    visuals["selected"] = field_test.make_curve("AF_PATCH_SELECTED", trace_test.raised_paths(selected_paths, inputs, 0.016), collection, materials["trace"], 0.0022)
    visuals["rejected"] = field_test.make_curve("AF_PATCH_REJECTED", trace_test.raised_paths(rejected_paths, inputs, 0.013), collection, materials["guide"], 0.0012)
    palette = patch_materials()
    visuals["regions"] = colored_mesh("AF_PATCH_REGIONS", inputs, collection, palette, region_indices(partition, len(palette)))
    visuals["validity"] = colored_mesh("AF_PATCH_VALIDITY", inputs, collection, validity_materials(), validity_indices(partition))
    return visuals


def render_specs():
    return (("candidate_front", {"skin", "anchors", "selected", "rejected"}, (0.0, -8.0, 1.25)),
            ("selected_front", {"skin", "anchors", "selected"}, (0.0, -8.0, 1.25)),
            ("regions_front", {"regions", "anchors", "selected"}, (0.0, -8.0, 1.25)),
            ("validity_front", {"validity", "anchors", "selected"}, (0.0, -8.0, 1.25)),
            ("regions_threequarter", {"regions", "anchors", "selected"}, (4.6, -7.0, 2.8)),
            ("regions_back", {"regions", "selected"}, (0.0, 8.0, 1.25)))


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
    names = [spec[0] for spec in render_specs()]
    images = [Image.open(folder / f"{name}.png").convert("RGB") for name in names]
    canvas = Image.new("RGB", (1440, 2160), (5, 8, 14))
    labels = ("Full candidate super-graph", "Selected path subset", "Extracted patch regions",
              "Green valid / orange tiny / magenta invalid", "Patch regions — three-quarter", "Patch regions — back")
    for index, (image, label) in enumerate(zip(images, labels)):
        paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_patch_comparison.png")


def paste_panel(canvas, image, label, index, draw_type):
    resized = image.resize((720, 720))
    x, y = (index % 2) * 720, (index // 2) * 720
    canvas.paste(resized, (x, y))
    draw = draw_type.Draw(canvas)
    draw.rectangle((x, y, x + 430, y + 38), fill=(5, 8, 14))
    draw.text((x + 12, y + 11), label, fill=(232, 238, 248))


def metrics_payload(groups, selected, partition, inputs):
    kinds = {kind: sum(patch.kind == kind for patch in partition.patches)
             for kind in ("valid", "tiny", "invalid")}
    area_values = {kind: sum(patch.area for patch in partition.patches if patch.kind == kind)
                   for kind in kinds}
    total = sum(area_values.values())
    ratios = {kind: value / max(total, 1.0e-12) for kind, value in area_values.items()}
    return {"vertices": len(inputs.vertices), "triangles": len(inputs.faces),
            "candidate_groups": len(groups), "selected_groups": int(selected.sum()),
            "rejected_groups": int((~selected).sum()), "patches": len(partition.patches),
            "patch_kinds": kinds, "patch_area_ratios": ratios, "selection_score": partition.score}


def save_outputs(args, metrics, visuals):
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    visuals["skin"]["af_topology_patch_test"] = json.dumps(metrics, sort_keys=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output), copy=True)


def field_data(args):
    root, skin = guide_test.scene_inputs()
    anchors, guides = field_test.anchor_objects(), field_test.open_guides(root)
    collection = guide_test.make_collection("AF_TOPOLOGY_PATCH_TEST")
    work = guide_test.duplicate_work_mesh(skin, args.target_faces, collection)
    inputs = field_test.field_inputs(work)
    rows = field_test.anchor_rows(anchors, inputs) + field_test.guide_rows(guides, anchors, inputs)
    solution = field_test.solve_field(inputs, rows)
    return skin, anchors, collection, inputs, solution


def trace_data(anchors, inputs, solution):
    values = trace_test.face_field(solution, inputs)
    records = trace_test.singularities(solution, values, inputs, False)
    adjacency = trace_test.face_adjacency(inputs.faces)
    _mirrored, _seeds, results = trace_test.trace_inputs(anchors, records, values, adjacency, inputs, False)
    return adjacency, results


def partition_data(anchors, adjacency, results, inputs):
    groups = trace_groups(results)
    tree = face_tree(inputs)
    anchor_mask = anchor_barrier(anchors, tree, adjacency, len(inputs.faces))
    masks = group_masks(groups, tree, adjacency, len(inputs.faces))
    pairs, areas = face_pairs(adjacency), triangle_areas(inputs)
    selected, partition = select_groups(anchor_mask, masks, groups, pairs, areas, inputs)
    partition = clean_tiny_islands(partition, pairs, areas, inputs)
    return groups, selected, partition


def build_prototype(args):
    skin, anchors, collection, inputs, solution = field_data(args)
    adjacency, results = trace_data(anchors, inputs, solution)
    groups, selected, partition = partition_data(anchors, adjacency, results, inputs)
    return skin, anchors, collection, inputs, groups, selected, partition


def finish_prototype(args, data):
    skin, anchors, collection, inputs, groups, selected, partition = data
    metrics = metrics_payload(groups, selected, partition, inputs)
    visuals = create_visuals(skin, anchors, groups, selected, partition, inputs, collection)
    camera = prepare_render(visuals)
    render_all(camera, visuals, args.render_dir)
    save_outputs(args, metrics, visuals)
    print("AF_TOPOLOGY_PATCH_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
