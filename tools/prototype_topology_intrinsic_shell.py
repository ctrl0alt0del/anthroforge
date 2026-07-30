import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_field as field_test
import prototype_topology_global_layout as global_test
import prototype_topology_guides as guide_test


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--target-faces", type=int, default=3600)
    parser.add_argument("--selected-loops", type=int, default=18)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def make_proxy(skin, collection):
    proxy = skin.copy()
    proxy.data = skin.data.copy()
    proxy.name = "AF_INTRINSIC_SHELL_PROXY"
    collection.objects.link(proxy)
    smooth_proxy(proxy)
    return proxy


def smooth_proxy(proxy):
    modifier = proxy.modifiers.new("AF_INTRINSIC_SCALE_SMOOTH", "SMOOTH")
    modifier.factor, modifier.iterations = 0.5, 12
    guide_test._activate(proxy)
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def run_quadriflow(proxy, target_faces):
    guide_test._activate(proxy)
    proxy.use_mesh_mirror_x = False
    bpy.ops.object.quadriflow_remesh(use_mesh_symmetry=False, use_preserve_sharp=False,
                                    use_preserve_boundary=False, preserve_attributes=False,
                                    smooth_normals=True, mode="FACES", target_faces=target_faces, seed=0)


def project_to_skin(proxy, skin):
    modifier = proxy.modifiers.new("AF_INTRINSIC_PROJECT", "SHRINKWRAP")
    modifier.wrap_method, modifier.wrap_mode = "NEAREST_SURFACEPOINT", "ON_SURFACE"
    modifier.target = skin
    guide_test._activate(proxy)
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def world_vertices(obj):
    return np.asarray([obj.matrix_world @ vertex.co for vertex in obj.data.vertices], dtype=np.float64)


def edge_vertices(obj):
    return np.asarray([edge.vertices[:] for edge in obj.data.edges], dtype=np.int32)


def quad_vertices(obj):
    return tuple(tuple(polygon.vertices) for polygon in obj.data.polygons if len(polygon.vertices) == 4)


def edge_lookup(edges):
    return {tuple(sorted(map(int, edge))): index for index, edge in enumerate(edges)}


def quad_edge_ids(vertices, lookup):
    pairs = zip(vertices, vertices[1:] + vertices[:1])
    return tuple(lookup[tuple(sorted((int(first), int(second))))] for first, second in pairs)


def connect_pair(adjacency, first, second):
    adjacency[first].add(second)
    adjacency[second].add(first)


def opposite_adjacency(obj, edges):
    lookup = edge_lookup(edges)
    adjacency = [set() for _edge in edges]
    for quad in quad_vertices(obj):
        ids = quad_edge_ids(quad, lookup)
        connect_pair(adjacency, ids[0], ids[2])
        connect_pair(adjacency, ids[1], ids[3])
    return tuple(tuple(sorted(values)) for values in adjacency)


def component_order(start, adjacency):
    order, previous, current = [], -1, int(start)
    for _step in range(len(adjacency) + 1):
        if current in order:
            break
        order.append(current)
        options = [value for value in adjacency[current] if value != previous]
        previous, current = current, options[0] if options else -1
        if current < 0:
            break
    return tuple(order)


def chord_components(adjacency):
    pending, values = set(range(len(adjacency))), []
    while pending:
        component = component_order(min(pending), adjacency)
        pending.difference_update(component)
        if len(component) > 2:
            values.append(component)
    return tuple(values)


def edge_midpoints(vertices, edges):
    return vertices[edges].mean(axis=1)


def chord_loops(obj):
    vertices, edges = world_vertices(obj), edge_vertices(obj)
    adjacency = opposite_adjacency(obj, edges)
    midpoints = edge_midpoints(vertices, edges)
    return tuple(midpoints[np.asarray(component)] for component in chord_components(adjacency)), adjacency


def closed_length(points):
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def loop_distance(points, selected):
    from scipy.spatial import cKDTree
    distances = cKDTree(np.vstack(selected)).query(points, workers=-1)[0]
    return float(np.quantile(distances, 0.55))


def select_chords(loops, count):
    selected = [max(loops, key=closed_length)]
    remaining = [loop for loop in loops if loop is not selected[0]]
    while remaining and len(selected) < count:
        index = max(range(len(remaining)), key=lambda item: loop_distance(remaining[item], selected))
        selected.append(remaining.pop(index))
    return tuple(selected)


def anchor_points(anchors):
    return np.vstack([field_test.object_world_vertices(anchor) for anchor in anchors])


def clearance_mask(points, tree, clearance):
    return tree.query(points, workers=-1)[0] > clearance


def cyclic_true_runs(mask):
    if mask.all():
        return (np.arange(len(mask)),)
    start = int(np.flatnonzero(~mask)[0])
    ordered = np.roll(np.arange(len(mask)), -start)
    values = mask[ordered]
    changes = np.flatnonzero(values != np.roll(values, 1))
    return tuple(ordered[first:second] for first, second in zip(changes[::2], changes[1::2]) if second - first > 1)


def clipped_chords(loops, anchors, diagonal):
    from scipy.spatial import cKDTree
    tree = cKDTree(anchor_points(anchors))
    values, endpoints = [], []
    for loop in loops:
        parts = [loop[run] for run in cyclic_true_runs(clearance_mask(loop, tree, diagonal / 55.0))]
        values.extend(part for part in parts if len(part) > 1)
        endpoints.extend(point for part in parts for point in (part[0], part[-1]))
    return tuple(values), np.asarray(endpoints)


def mesh_edge_lines(obj):
    vertices, edges = world_vertices(obj), edge_vertices(obj)
    return tuple((vertices[edge], False) for edge in edges)


def raised_polyline(points, bvh, offset, closed):
    values = np.vstack((points, points[0])) if closed else points
    hits = [guide_test._nearest(bvh, point) for point in values]
    return np.asarray([np.asarray(hit[0]) + (np.asarray(hit[1]) * offset) for hit in hits])


def raised_chords(loops, bvh, offset, closed):
    return tuple((raised_polyline(points, bvh, offset, closed), False) for points in loops)


def materials(skin):
    skin.data.materials.clear()
    skin.data.materials.append(guide_test.material("AF_INTRINSIC_SKIN", (0.04, 0.055, 0.08)))
    return {"dense": guide_test.material("AF_INTRINSIC_DENSE", (0.12, 0.35, 0.48), 0.5),
            "loop": guide_test.material("AF_INTRINSIC_LOOP", (0.02, 0.9, 1.0), 2.2),
            "anchor": guide_test.material("AF_INTRINSIC_ANCHOR", (1.0, 0.24, 0.035), 2.4),
            "endpoint": guide_test.material("AF_INTRINSIC_ENDPOINT", (1.0, 0.86, 0.04), 3.0)}


def create_visuals(skin, proxy, anchors, loops, endpoints, inputs, collection):
    values = materials(skin)
    visuals = {"skin": skin}
    visuals["dense"] = field_test.make_curve("AF_INTRINSIC_DENSE", mesh_edge_lines(proxy), collection, values["dense"], 0.0007)
    visuals["loops"] = field_test.make_curve("AF_INTRINSIC_LOOPS", raised_chords(loops, inputs.bvh, 0.012, False), collection, values["loop"], 0.0025)
    visuals["anchors"] = field_test.make_curve("AF_INTRINSIC_ANCHORS", global_test.offset_anchor_lines(anchors, inputs, 0.015), collection, values["anchor"], 0.0037)
    screen = endpoints[:, (0, 2)] if len(endpoints) else np.empty((0, 2))
    markers = global_test.marker_lines(screen, inputs, inputs.diagonal / 190.0, 0.019)
    visuals["endpoints"] = field_test.make_curve("AF_INTRINSIC_ENDPOINTS", markers, collection, values["endpoint"], 0.0024)
    return visuals


def render_specs():
    common = {"skin", "loops", "anchors", "endpoints"}
    return (("dense_front", {"skin", "dense", "anchors"}, (0.0, -8.0, 1.25)),
            ("intrinsic_front", common, (0.0, -8.0, 1.25)),
            ("intrinsic_threequarter", common, (4.6, -7.0, 2.8)),
            ("intrinsic_back", {"skin", "loops"}, (0.0, 8.0, 1.25)))


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
    labels = ("Temporary complete-shell quad scaffold", "Sparse intrinsic loops + hard anchors",
              "Intrinsic loops - three-quarter", "Intrinsic loops cover the back")
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        field_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_intrinsic_shell_comparison.png")


def vertex_symmetry_error(obj):
    from scipy.spatial import cKDTree
    vertices = world_vertices(obj)
    reflected = vertices.copy()
    reflected[:, 0] *= -1.0
    return float(cKDTree(vertices).query(reflected, workers=-1)[0].max())


def coverage_error(proxy, loops):
    from scipy.spatial import cKDTree
    vertices = world_vertices(proxy)
    return float(cKDTree(np.vstack(loops)).query(vertices, workers=-1)[0].max())


def metrics_payload(proxy, loops, selected, clipped, endpoints, adjacency, anchors):
    polygons = tuple(proxy.data.polygons)
    return {"algorithm": "intrinsic_poly_chord_shell_v1", "proxy_vertices": len(proxy.data.vertices),
            "proxy_faces": len(polygons), "all_proxy_faces_quads": all(len(face.vertices) == 4 for face in polygons),
            "poly_chords": len(loops), "selected_poly_chords": len(selected),
            "clipped_polyline_parts": len(clipped), "anchor_transition_endpoints": len(endpoints),
            "anchor_rows_preserved": sum(len(field_test.object_ring_lines(anchor)) for anchor in anchors),
            "irregular_dual_edges": sum(len(values) != 2 for values in adjacency),
            "symmetry_error": vertex_symmetry_error(proxy), "coverage_error": coverage_error(proxy, selected)}


def build_prototype(args):
    _root, skin = guide_test.scene_inputs()
    anchors = field_test.anchor_objects()
    collection = guide_test.make_collection("AF_TOPOLOGY_INTRINSIC_SHELL_TEST")
    proxy = make_proxy(skin, collection)
    run_quadriflow(proxy, args.target_faces)
    project_to_skin(proxy, skin)
    inputs = field_test.field_inputs(proxy)
    loops, adjacency = chord_loops(proxy)
    selected = select_chords(loops, args.selected_loops)
    clipped, endpoints = clipped_chords(selected, anchors, inputs.diagonal)
    return skin, proxy, anchors, collection, inputs, loops, adjacency, selected, clipped, endpoints


def finish_prototype(args, data):
    skin, proxy, anchors, collection, inputs, loops, adjacency, selected, clipped, endpoints = data
    metrics = metrics_payload(proxy, loops, selected, clipped, endpoints, adjacency, anchors)
    visuals = create_visuals(skin, proxy, anchors, clipped, endpoints, inputs, collection)
    render_all(prepare_render(visuals), visuals, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    skin["af_topology_intrinsic_shell_test"] = json.dumps(metrics, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)
    print("AF_TOPOLOGY_INTRINSIC_SHELL", json.dumps(metrics, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish_prototype(args, build_prototype(args))


if __name__ == "__main__":
    main()
