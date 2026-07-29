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
class GuideCycle:
    name: str
    indices: np.ndarray
    targets: np.ndarray
    closed: bool


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=6000)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def duplicate_for_quadriflow(skin, collection):
    cage = skin.copy()
    cage.data = skin.data.copy()
    cage.name = "AF_TOPO_QUADRIFLOW_WORK"
    collection.objects.link(cage)
    return cage


def run_quadriflow(cage, target_faces):
    guide_test._activate(cage)
    bpy.ops.object.quadriflow_remesh(
        mode="FACES", target_faces=target_faces, use_mesh_symmetry=True,
        use_preserve_sharp=False, use_preserve_boundary=False, seed=0,
    )
    cage.data.name = "AF_TOPO_LOW_CAGE_MESH"


def world_vertices(obj):
    return np.asarray([obj.matrix_world @ vertex.co for vertex in obj.data.vertices], dtype=np.float64)


def edge_arrays(obj):
    edges = np.asarray([edge.vertices[:] for edge in obj.data.edges], dtype=np.int32)
    return edges


def weighted_graph(vertices, edges, guide_points, reserved):
    sparse = _sparse_module()
    distances = _nearest_distances(vertices, guide_points)
    lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    scale = max(float(np.median(lengths)), 1.0e-6)
    penalties = 1.0 + 18.0 * np.square(np.mean(distances[edges], axis=1) / (3.0 * scale))
    penalties *= np.where(np.max(distances[edges], axis=1) > (4.0 * scale), 1.0e5, 1.0)
    penalties *= _reserved_penalties(edges, reserved)
    return _symmetric_graph(len(vertices), edges, lengths * penalties, sparse)


def _sparse_module():
    from scipy import sparse
    return sparse


def _nearest_distances(vertices, points):
    from scipy.spatial import cKDTree
    return cKDTree(points).query(vertices, workers=-1)[0]


def _reserved_penalties(edges, reserved):
    if not reserved:
        return np.ones(len(edges), dtype=np.float64)
    occupied = np.fromiter((index in reserved for index in edges.ravel()), bool).reshape((-1, 2))
    return np.where(np.any(occupied, axis=1), 25.0, 1.0)


def _symmetric_graph(count, edges, weights, sparse):
    rows = np.concatenate((edges[:, 0], edges[:, 1]))
    cols = np.concatenate((edges[:, 1], edges[:, 0]))
    data = np.concatenate((weights, weights))
    return sparse.csr_matrix((data, (rows, cols)), shape=(count, count))


def build_cycles(guides, source_bvh, vertices, edges):
    cycles, reserved = [], set()
    for guide in (item for item in guides if item.closed):
        cycle = _build_cycle(guide, source_bvh, vertices, edges, reserved)
        if cycle is not None:
            cycles.append(cycle)
            reserved.update(map(int, cycle.indices))
    return tuple(cycles)


def _build_cycle(guide, source_bvh, vertices, edges, reserved):
    projected = guide_test.projected_guide(guide, source_bvh)
    if projected is None:
        return None
    points = resample_loop(projected[0], 192)
    anchors = nearest_indices(vertices, resample_loop(points, 24))
    graph = weighted_graph(vertices, edges, points, reserved)
    indices = join_paths(graph, anchors)
    if len(indices) < 4:
        return None
    targets = nearest_targets(vertices[indices], resample_loop(points, 512))
    cycle = GuideCycle(guide.name, indices, targets, is_simple_cycle(indices, edges))
    accepted, stats = cycle_diagnostics(cycle, vertices, edges, points)
    print("AF_TOPO_CYCLE", guide.name, json.dumps(stats, sort_keys=True), flush=True)
    return cycle if accepted else None


def acceptable_cycle(cycle, vertices, edges, guide_points):
    return cycle_diagnostics(cycle, vertices, edges, guide_points)[0]


def cycle_diagnostics(cycle, vertices, edges, guide_points):
    lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    movements = np.linalg.norm(vertices[cycle.indices] - cycle.targets, axis=1)
    scale = max(float(np.median(lengths)), 1.0e-6)
    coverage = _nearest_distances(guide_points, vertices[cycle.indices])
    accepted = bool(cycle.closed and movements.max() <= (5.0 * scale) and coverage.max() <= (3.0 * scale))
    stats = {"accepted": accepted, "vertices": len(cycle.indices), "simple": bool(cycle.closed)}
    stats.update({"edge": scale, "move_max": float(movements.max()), "coverage_max": float(coverage.max())})
    return accepted, stats


def resample_loop(points, count):
    closed = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    samples = np.linspace(0.0, cumulative[-1], count, endpoint=False)
    return np.column_stack([np.interp(samples, cumulative, closed[:, axis]) for axis in range(3)])


def nearest_indices(vertices, points):
    from scipy.spatial import cKDTree
    return cKDTree(vertices).query(points, workers=-1)[1].astype(np.int32)


def join_paths(graph, anchors):
    result, blocked = [], set()
    for first, second in _anchor_pairs(anchors):
        path = _shortest_path(graph, int(first), int(second), blocked)
        if len(path) < 2:
            return np.empty(0, dtype=np.int32)
        result.extend(map(int, path[:-1]))
        blocked.update(map(int, path[:-1]))
    return np.asarray(result, dtype=np.int32)


def _anchor_pairs(anchors):
    compact = anchors[np.concatenate(([True], anchors[1:] != anchors[:-1]))]
    return zip(compact, np.roll(compact, -1))


def _shortest_path(graph, start, end, blocked):
    from scipy.sparse.csgraph import dijkstra
    local = graph_without_vertices(graph, blocked - {start, end})
    _distances, predecessors = dijkstra(local, indices=start, return_predecessors=True)
    return reconstruct_path(predecessors, start, end)


def graph_without_vertices(graph, blocked):
    if not blocked:
        return graph
    local = graph.tolil(copy=True)
    indices = np.fromiter(blocked, dtype=np.int32)
    local[indices, :], local[:, indices] = 0.0, 0.0
    return local.tocsr()


def reconstruct_path(predecessors, start, end):
    path, current = [end], end
    while current != start and current >= 0:
        current = int(predecessors[current])
        path.append(current)
    return np.asarray(path[::-1] if current == start else (), dtype=np.int32)


def nearest_targets(vertices, points):
    from scipy.spatial import cKDTree
    return points[cKDTree(points).query(vertices, workers=-1)[1]]


def is_simple_cycle(indices, edges):
    cycle_edges = {_edge_key(a, b) for a, b in zip(indices, np.roll(indices, -1))}
    mesh_edges = {_edge_key(a, b) for a, b in edges}
    return len(indices) == len(set(map(int, indices))) and cycle_edges <= mesh_edges


def _edge_key(first, second):
    return tuple(sorted((int(first), int(second))))


def fit_cycles(cage, cycles, source_bvh):
    vertices = world_vertices(cage)
    fixed = _cycle_targets(cycles)
    for index, target in fixed.items():
        vertices[index] = target
    neighbors = vertex_neighbors(len(vertices), edge_arrays(cage))
    vertices = relax_on_surface(vertices, neighbors, fixed, source_bvh, 8)
    set_world_vertices(cage, vertices)


def _cycle_targets(cycles):
    grouped = {}
    for cycle in cycles:
        for index, target in zip(cycle.indices, cycle.targets):
            grouped.setdefault(int(index), []).append(target)
    return {index: np.mean(targets, axis=0) for index, targets in grouped.items()}


def vertex_neighbors(count, edges):
    neighbors = [[] for _index in range(count)]
    for first, second in edges:
        neighbors[int(first)].append(int(second))
        neighbors[int(second)].append(int(first))
    return tuple(np.asarray(items, dtype=np.int32) for items in neighbors)


def relax_on_surface(vertices, neighbors, fixed, bvh, iterations):
    current = vertices.copy()
    movable = local_relaxation_mask(neighbors, fixed, 3)
    for _iteration in range(iterations):
        current = relax_step(current, neighbors, movable)
        current = project_vertices(current, bvh, movable)
        for index, target in fixed.items():
            current[index] = target
    return current


def local_relaxation_mask(neighbors, fixed, rings):
    distance = np.full(len(neighbors), -1, dtype=np.int32)
    frontier = set(fixed)
    distance[list(frontier)] = 0
    for ring in range(1, rings + 1):
        frontier = {int(item) for index in frontier for item in neighbors[index] if distance[item] < 0}
        distance[list(frontier)] = ring
    return (distance > 0) & (distance < rings)


def relax_step(vertices, neighbors, movable):
    averages = np.asarray([vertices[items].mean(axis=0) if len(items) else vertices[i] for i, items in enumerate(neighbors)])
    result = vertices.copy()
    result[movable] = (0.85 * vertices[movable]) + (0.15 * averages[movable])
    return result


def project_vertices(vertices, bvh, mask):
    result = vertices.copy()
    for index in np.flatnonzero(mask):
        hit = guide_test._nearest(bvh, vertices[index])
        if hit is not None:
            result[index] = hit[0]
    return result


def set_world_vertices(obj, vertices):
    inverse = obj.matrix_world.inverted()
    local = np.asarray([inverse @ Vector(point) for point in vertices], dtype=np.float64)
    obj.data.vertices.foreach_set("co", local.ravel())
    obj.data.update()


def duplicate_object(obj, name, collection):
    duplicate = obj.copy()
    duplicate.data = obj.data.copy()
    duplicate.name = name
    collection.objects.link(duplicate)
    return duplicate


def material_object(obj, value):
    obj.data.materials.clear()
    obj.data.materials.append(value)
    return obj


def make_wire(obj, name, collection, value, thickness):
    wire = material_object(duplicate_object(obj, name, collection), value)
    modifier = wire.modifiers.new("AF_TOPO_WIREFRAME", "WIREFRAME")
    modifier.thickness, modifier.use_replace = thickness, True
    return wire


def make_smooth_preview(obj, source, collection, value):
    preview = material_object(duplicate_object(obj, "AF_TOPO_SMOOTH_PREVIEW", collection), value)
    subdivision = preview.modifiers.new("AF_TOPO_SUBDIVISION", "SUBSURF")
    subdivision.levels = subdivision.render_levels = 2
    shrinkwrap = preview.modifiers.new("AF_TOPO_PROJECT", "SHRINKWRAP")
    shrinkwrap.wrap_method, shrinkwrap.target = "NEAREST_SURFACEPOINT", source
    return preview


def cycle_lines(cycles, vertices):
    return [(vertices[cycle.indices], True) for cycle in cycles]


def topology_metrics(raw, guided, cycles, source_bvh):
    vertices = world_vertices(guided)
    deviations = [_nearest_distance(source_bvh, point) for point in vertices]
    polygons = tuple(len(face.vertices) for face in guided.data.polygons)
    movements = cycle_movements(raw, guided, cycles)
    return {
        "vertices": len(vertices), "faces": len(polygons),
        "quad_ratio": float(np.mean(np.asarray(polygons) == 4)),
        "closed_cycles": sum(cycle.closed for cycle in cycles),
        "guide_cycles": len(cycles), "surface_max_error": max(deviations),
        "raw_volume": mesh_volume(raw), "guided_volume": mesh_volume(guided),
        "cycle_movements": movements,
    }


def cycle_movements(raw, guided, cycles):
    before, after = world_vertices(raw), world_vertices(guided)
    return {
        cycle.name: {
            "mean": float(np.mean(np.linalg.norm(after[cycle.indices] - before[cycle.indices], axis=1))),
            "max": float(np.max(np.linalg.norm(after[cycle.indices] - before[cycle.indices], axis=1))),
        } for cycle in cycles
    }


def mesh_volume(obj):
    obj.data.calc_loop_triangles()
    vertices = world_vertices(obj)
    faces = np.asarray([triangle.vertices[:] for triangle in obj.data.loop_triangles], dtype=np.int32)
    products = np.einsum("ij,ij->i", vertices[faces[:, 0]], np.cross(vertices[faces[:, 1]], vertices[faces[:, 2]]))
    return abs(float(products.sum() / 6.0))


def _nearest_distance(bvh, point):
    hit = guide_test._nearest(bvh, point)
    return float(np.linalg.norm(np.asarray(hit[0]) - point)) if hit else math.inf


def build_visuals(skin, raw, guided, cycles, guides, source_bvh, collection):
    values = visual_materials(skin)
    raw_solid = material_object(raw, values["solid"])
    guided_solid = material_object(guided, values["solid"])
    raw_wire = make_wire(raw, "AF_TOPO_RAW_WIRE", collection, values["raw_wire"], 0.0025)
    guided_wire = make_wire(guided, "AF_TOPO_GUIDED_WIRE", collection, values["wire"], 0.003)
    preview = make_smooth_preview(guided, skin, collection, values["preview"])
    lines = guide_test.curve_object("AF_TOPO_FITTED_LOOPS", cycle_lines(cycles, world_vertices(guided)), collection, values["loop"], 0.006)
    requested = requested_guide_object(guides, source_bvh, collection, values["requested"])
    return skin, raw_solid, guided_solid, raw_wire, guided_wire, preview, requested, lines


def requested_guide_object(guides, source_bvh, collection, value):
    loops = tuple(guide for guide in guides if guide.closed)
    lines = guide_test.guide_lines(loops, source_bvh, 0.008)
    return guide_test.curve_object("AF_TOPO_REQUESTED_LOOPS", lines, collection, value, 0.003)


def visual_materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_TOPO_SOURCE_SKIN", (0.18, 0.22, 0.28)))
    return {
        "solid": guide_test.material("AF_TOPO_CAGE_SOLID", (0.06, 0.10, 0.14)),
        "raw_wire": guide_test.material("AF_TOPO_RAW_EDGE", (0.95, 0.52, 0.08), 1.2),
        "wire": guide_test.material("AF_TOPO_GUIDED_EDGE", (0.05, 0.78, 1.0), 1.5),
        "preview": guide_test.material("AF_TOPO_PREVIEW", (0.38, 0.68, 0.82)),
        "requested": guide_test.material("AF_TOPO_REQUESTED_LOOP", (1.0, 0.45, 0.02), 1.4),
        "loop": guide_test.material("AF_TOPO_FITTED_LOOP", (1.0, 0.04, 0.03), 2.0),
    }


def prepare_render(objects):
    for obj in tuple(bpy.context.scene.objects):
        obj.hide_render = True
    guide_test._render_settings()
    camera = guide_test._camera()
    guide_test._lights()
    return camera, objects


def render_all(camera, objects, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    variants = render_variants(objects)
    for name, visible in variants.items():
        set_visibility(objects, visible)
        guide_test._render_view(camera, (0.0, -8.0, 1.25), folder / f"{name}_front.png")
    render_threequarter(camera, objects, variants, folder)
    make_contact_sheet(folder, tuple(variants))


def render_variants(objects):
    skin, raw, guided, raw_wire, guided_wire, preview, requested, loops = objects
    return {
        "source": {skin}, "raw_quadriflow": {raw, raw_wire},
        "guided_topology": {guided, guided_wire, requested, loops},
        "smooth_preview": {preview, guided_wire, requested, loops},
    }


def set_visibility(objects, visible):
    for obj in objects:
        obj.hide_render = obj not in visible


def render_threequarter(camera, objects, variants, folder):
    for name in ("guided_topology", "smooth_preview"):
        set_visibility(objects, variants[name])
        guide_test._render_view(camera, (4.6, -7.0, 2.8), folder / f"{name}_threequarter.png")


def make_contact_sheet(folder, names):
    from PIL import Image, ImageDraw
    images = [Image.open(folder / f"{name}_front.png").convert("RGB") for name in names]
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    labels = ("High-poly draft skin", "Raw QuadriFlow cage", "Guide-fitted low topology", "Subdivision preview")
    for index, (image, label) in enumerate(zip(images, labels)):
        paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_mesh_comparison.png")


def paste_panel(canvas, image, label, index, image_draw):
    x, y = (index % 2) * 720, (index // 2) * 720
    canvas.paste(image, (x, y))
    draw = image_draw.Draw(canvas)
    draw.rectangle((x, y, x + 390, y + 38), fill=(5, 8, 14))
    draw.text((x + 12, y + 10), label, fill=(235, 240, 248))


def save_outputs(path, metrics, guided):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    guided["af_topology_prototype"] = True
    guided["af_topology_prototype_stats"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=True)


def quadriflow_variants(skin, guides, source_bvh, collection, target_faces):
    raw = duplicate_for_quadriflow(skin, collection)
    run_quadriflow(raw, target_faces)
    raw.name = "AF_TOPO_RAW_CAGE"
    cage = duplicate_object(raw, "AF_TOPO_GUIDED_LOW_CAGE", collection)
    return raw, cage


def build_prototype(args):
    guide_test.ensure_runtime()
    root, skin = guide_test.scene_inputs()
    guides = guide_test.collect_guides(root)
    collection = guide_test.make_collection("AF_TOPOLOGY_MESH_TEST")
    source_vertices, source_faces, _normals = guide_test.mesh_arrays(skin)
    source_bvh = guide_test.surface_bvh(source_vertices, source_faces)
    raw, cage = quadriflow_variants(skin, guides, source_bvh, collection, args.target_faces)
    cycles = build_cycles(guides, source_bvh, world_vertices(cage), edge_arrays(cage))
    fit_cycles(cage, cycles, source_bvh)
    cage.name = "AF_TOPO_GUIDED_LOW_CAGE"
    return skin, raw, cage, cycles, guides, source_bvh, collection


def finish_prototype(args, data):
    skin, raw, guided, cycles, guides, source_bvh, collection = data
    metrics = topology_metrics(raw, guided, cycles, source_bvh)
    objects = build_visuals(skin, raw, guided, cycles, guides, source_bvh, collection)
    camera, objects = prepare_render(objects)
    render_all(camera, objects, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    save_outputs(args.output, metrics, guided)
    print("AF_TOPOLOGY_MESH_PROTOTYPE", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
