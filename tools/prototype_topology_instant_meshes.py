import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import bpy
import bmesh
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prototype_topology_annuli as annulus_test
import prototype_topology_field as field_test
import prototype_topology_global_layout as global_test
import prototype_topology_guides as guide_test
import prototype_topology_cube_shell as cube_test


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--target-vertices", type=int, default=4200)
    parser.add_argument("--target-faces", type=int, default=64000)
    parser.add_argument("--ignore-guides", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def remesh_arrays(work, anchors, vendor, count):
    bisect_left_half(work)
    vertices, faces, _normals = guide_test.mesh_arrays(work)
    faces = cut_guide_holes(vertices, faces, anchors)
    with tempfile.TemporaryDirectory(prefix="af_instant_") as folder:
        input_path, output_path = write_worker_input(folder, vertices, faces)
        run_worker(input_path, output_path, vendor, count)
        with np.load(output_path, allow_pickle=False) as values:
            return mirrored_output(
                values["vertices"].copy(), values["faces"].copy(), anchors)


def bisect_left_half(work):
    mesh = bmesh.new()
    mesh.from_mesh(work.data)
    geometry = tuple(mesh.verts) + tuple(mesh.edges) + tuple(mesh.faces)
    bmesh.ops.bisect_plane(mesh, geom=geometry, plane_co=(0.0, 0.0, 0.0),
                           plane_no=(1.0, 0.0, 0.0), clear_outer=True,
                           clear_inner=False, use_snap_center=True)
    bmesh.ops.triangulate(mesh, faces=tuple(mesh.faces))
    mesh.to_mesh(work.data)
    mesh.free()


def mirrored_output(vertices, faces, anchors):
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    snap_symmetry_boundary(vertices, faces, diagonal)
    mirrored = vertices.copy()
    mirrored[:, 0] *= -1.0
    parts = [(vertices, faces), (mirrored, faces[:, ::-1])]
    hybrid = cube_test.welded_hybrid(parts, 1.0e-6 * diagonal)
    return hybrid.vertices, hybrid.faces


def snap_symmetry_boundary(vertices, faces, diagonal):
    boundary = np.unique(boundary_edges(faces))
    near = boundary[np.abs(vertices[boundary, 0]) < 0.02 * diagonal]
    vertices[near, 0] = 0.0
    vertices[:, 0] = np.minimum(vertices[:, 0], 0.0)


def fill_unmatched_boundaries(hybrid, anchors):
    loops = cube_test.boundary_loops(boundary_edges(hybrid.faces))
    extras = unmatched_boundaries(loops, hybrid.vertices, anchors)
    mesh = hybrid_bmesh(hybrid)
    for loop in extras:
        fill_bmesh_loop(mesh, loop)
    return bmesh_hybrid(mesh)


def unmatched_boundaries(loops, vertices, anchors):
    pending = set(range(len(loops)))
    for anchor in anchors:
        center = global_test.outer_ring(anchor).mean(axis=0)
        match = min(pending, key=lambda index: np.linalg.norm(
            vertices[np.asarray(loops[index])].mean(axis=0) - center))
        pending.remove(match)
    return tuple(loops[index] for index in sorted(pending))


def hybrid_bmesh(hybrid):
    mesh = bmesh.new()
    for point in hybrid.vertices:
        mesh.verts.new(point)
    mesh.verts.ensure_lookup_table()
    for face in hybrid.faces:
        mesh.faces.new([mesh.verts[int(index)] for index in face])
    mesh.verts.index_update()
    mesh.edges.index_update()
    return mesh


def fill_bmesh_loop(mesh, loop):
    first_ids, second_ids = mirrored_loop_chains(mesh, loop)
    if len(first_ids) != len(second_ids):
        raise RuntimeError("Symmetry slit chains have different lengths.")
    first = tuple(mesh.verts[int(index)] for index in first_ids)
    second = tuple(mesh.verts[int(index)] for index in second_ids)
    centers = centerline_vertices(mesh, first, second)
    add_slit_cap(mesh, first, second, centers, False)
    for index in range(1, len(first) - 2):
        add_slit_rows(mesh, first, second, centers, index)
    add_slit_cap(mesh, first, second, centers, True)


def centerline_vertices(mesh, first, second):
    values = {}
    for index in range(1, len(first) - 1):
        point = 0.5 * (first[index].co + second[index].co)
        values[index] = mesh.verts.new(point)
    return values


def add_slit_cap(mesh, first, second, centers, bottom):
    index = len(first) - 2 if bottom else 1
    endpoint = first[-1] if bottom else first[0]
    ids = (centers[index], first[index], endpoint, second[index])
    mesh.faces.new(ids)


def add_slit_rows(mesh, first, second, centers, index):
    left = (centers[index], first[index], first[index + 1], centers[index + 1])
    right = (second[index], centers[index], centers[index + 1], second[index + 1])
    mesh.faces.new(left)
    mesh.faces.new(right)


def mirrored_loop_chains(mesh, loop):
    fixed = [index for index, vertex in enumerate(loop)
             if abs(float(mesh.verts[int(vertex)].co.x)) < 1.0e-8]
    if len(fixed) != 2:
        raise RuntimeError("Unmatched boundary is not a symmetry slit.")
    start, end = fixed
    first = loop[start:end + 1]
    second = tuple(reversed(loop[end:] + loop[:start + 1]))
    if chain_x(mesh, first) > chain_x(mesh, second):
        first, second = second, first
    return first, second


def chain_x(mesh, chain):
    return float(np.mean([mesh.verts[int(index)].co.x for index in chain]))


def bmesh_hybrid(mesh):
    bmesh.ops.recalc_face_normals(mesh, faces=tuple(mesh.faces))
    mesh.verts.index_update()
    vertices = np.asarray([vertex.co[:] for vertex in mesh.verts], dtype=np.float64)
    faces = np.asarray([tuple(vertex.index for vertex in face.verts)
                        for face in mesh.faces], dtype=np.int32)
    mesh.free()
    if faces.ndim != 2 or faces.shape[1] != 4:
        raise RuntimeError("Boundary repair did not produce pure quads.")
    return cube_test.HybridMesh(vertices, faces)


def ring_frame(ring):
    center = ring.mean(axis=0)
    _values, vectors = np.linalg.eigh(np.cov((ring - center).T))
    return center, vectors[:, -1], vectors[:, -2], vectors[:, 0]


def local_points(points, center, first, second):
    relative = points - center
    return np.column_stack((relative @ first, relative @ second))


def guide_face_mask(vertices, faces, ring):
    center, first, second, normal = ring_frame(ring)
    polygon = local_points(ring, center, first, second) * 1.20
    centers = vertices[faces].mean(axis=1)
    local = local_points(centers, center, first, second)
    radius = np.linalg.norm(ring - center, axis=1).max()
    nearby = np.linalg.norm(centers - center, axis=1) < 1.8 * radius
    depth = np.abs((centers - center) @ normal) < 0.55 * radius
    inside = np.asarray([global_test.point_in_polygon(point, polygon) for point in local])
    return nearby & depth & inside


def cut_guide_holes(vertices, faces, anchors):
    if not anchors:
        return faces
    masks = [guide_face_mask(vertices, faces, global_test.outer_ring(anchor))
             for anchor in anchors]
    removed = np.logical_or.reduce(masks)
    return faces[~removed]


def write_worker_input(folder, vertices, faces):
    input_path, output_path = Path(folder, "input.npz"), Path(folder, "output.npz")
    np.savez(input_path, vertices=vertices.astype(np.float32), faces=faces.astype(np.int32))
    return input_path, output_path


def run_worker(input_path, output_path, vendor, count):
    python = Path(sys.prefix, "bin", "python.exe")
    worker = Path(__file__).with_name("prototype_topology_instant_worker.py")
    command = [str(python), str(worker), "--input", str(input_path), "--output", str(output_path),
               "--vendor", vendor, "--target-vertices", str(count)]
    subprocess.run(command, check=True)


def clean_faces(faces):
    values = np.asarray(faces, dtype=np.int32)
    return tuple(tuple(int(value) for value in row if value >= 0) for row in values)


def create_mesh(vertices, faces, collection):
    mesh = bpy.data.meshes.new("AF_INSTANT_MESH")
    mesh.from_pydata(np.asarray(vertices).tolist(), [], clean_faces(faces))
    mesh.update()
    obj = bpy.data.objects.new("AF_INSTANT_MESH", mesh)
    collection.objects.link(obj)
    return obj


def object_quad_arrays(obj):
    vertices = np.asarray([vertex.co[:] for vertex in obj.data.vertices], dtype=np.float64)
    faces = np.asarray([tuple(polygon.vertices) for polygon in obj.data.polygons], dtype=np.int32)
    return vertices, faces


def boundary_edges(faces):
    values = np.vstack([faces[:, (index, (index + 1) % 4)] for index in range(4)])
    unique, counts = np.unique(np.sort(values, axis=1), axis=0, return_counts=True)
    return unique[counts == 1]


def guide_transitions(vertices, faces, anchors):
    loops = cube_test.boundary_loops(boundary_edges(faces))
    pairs = cube_test.matched_boundaries(loops, vertices, anchors)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    values = [make_transition(anchor.name, pair, diagonal)
              for anchor, pair in zip(anchors, pairs)]
    return mirror_paired_transitions(values, diagonal)


def interior_transitions(vertices, faces, anchors):
    loops = cube_test.boundary_loops(boundary_edges(faces))
    extras = unmatched_boundaries(loops, vertices, anchors)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    values = [inner_transition(loop, vertices, anchors, diagonal) for loop in extras]
    return mirror_paired_transitions(values, diagonal)


def inner_transition(loop, vertices, anchors, diagonal):
    boundary = vertices[np.asarray(loop)]
    anchor = min(anchors, key=lambda item: np.linalg.norm(
        inner_ring(item).mean(axis=0) - boundary.mean(axis=0)))
    return make_transition(f"{anchor.name}_INNER", (boundary, inner_ring(anchor)), diagonal)


def inner_ring(anchor):
    rings = cube_test.ordered_anchor_rings(anchor)
    return min(rings, key=global_test.ring_perimeter)


def make_transition(name, pair, diagonal):
    boundary, ring = pair
    if abs(float(boundary[:, 0].mean())) > 1.0e-5 * diagonal:
        return side_transition(name, boundary, ring)
    first = cube_test.canonical_loop(boundary)
    second = cube_test.align_loop(first, ring)
    vertices = np.vstack((first, second))
    faces = equal_transition_faces(len(first)) if len(first) == len(second) else (
        cube_test.centered_transition_faces(first, second))
    cube_test.validate_transition_boundary(faces, len(first), len(second))
    return cube_test.Transition(name, vertices, faces)


def equal_transition_faces(count):
    return np.asarray([(index, (index + 1) % count,
                        count + ((index + 1) % count), count + index)
                       for index in range(count)], dtype=np.int32)


def side_transition(name, boundary, ring):
    first = cube_test.canonical_loop(boundary)
    second = cube_test.align_loop(first, ring)
    if abs(len(first) - len(second)) < 4:
        return cube_test.transition_mesh(name, first, second)
    middle = intermediate_ring(first, second)
    outer = cube_test.transition_mesh(name, first, middle)
    inner = cube_test.transition_mesh(name, middle, second)
    diagonal = float(np.linalg.norm(first.max(axis=0) - first.min(axis=0)))
    merged = cube_test.welded_hybrid(
        ((outer.vertices, outer.faces), (inner.vertices, inner.faces)), 1.0e-7 * diagonal)
    return cube_test.Transition(name, merged.vertices, merged.faces)


def intermediate_ring(first, second):
    count = intermediate_count(len(first), len(second))
    first_samples = cube_test.loop_samples(first, count)
    second_samples = cube_test.loop_samples(second, count)
    return 0.5 * (first_samples + second_samples)


def intermediate_count(first, second):
    parity = first % 2
    estimate = int(round(0.5 * (first + second)))
    return estimate if estimate % 2 == parity else estimate + 1


def transition_center(item):
    return item.vertices.mean(axis=0)


def reflected_center(item):
    value = transition_center(item).copy()
    value[0] *= -1.0
    return value


def mirror_paired_transitions(values, diagonal):
    pending = {index for index, item in enumerate(values)
               if transition_center(item)[0] > 1.0e-5 * diagonal}
    for index, item in enumerate(values):
        if transition_center(item)[0] < -1.0e-5 * diagonal:
            mirror_one_transition(values, index, pending, diagonal)
    return tuple(values)


def mirror_one_transition(values, source, pending, diagonal):
    if not pending:
        return
    target = min(pending, key=lambda index: np.linalg.norm(
        transition_center(values[index]) - reflected_center(values[source])))
    error = np.linalg.norm(transition_center(values[target]) - reflected_center(values[source]))
    if error < 0.02 * diagonal:
        values[target] = cube_test.mirrored_transition(values[source], values[target])
        pending.remove(target)


def stitched_mesh(obj, anchors, collection):
    vertices, faces = object_quad_arrays(obj)
    transitions = guide_transitions(vertices, faces, anchors)
    parts = [(vertices, faces)]
    parts.extend((item.vertices, item.faces) for item in transitions)
    parts.extend(cube_test.anchor_mesh(anchor) for anchor in anchors)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    hybrid = cube_test.welded_hybrid(parts, 1.0e-6 * diagonal)
    result = create_mesh(hybrid.vertices, hybrid.faces, collection)
    result.name = "AF_INSTANT_STITCHED"
    return result


def materials(obj):
    obj.data.materials.append(guide_test.material("AF_INSTANT_SURFACE", (0.025, 0.06, 0.10)))
    return {"wire": guide_test.material("AF_INSTANT_WIRE", (0.02, 0.92, 1.0), 2.0),
            "anchor": guide_test.material("AF_INSTANT_ANCHOR", (1.0, 0.20, 0.03), 2.6)}


def create_visuals(obj, anchors, collection):
    values = materials(obj)
    wire = annulus_test.make_wire_object(obj, collection, values["wire"])
    anchor = field_test.make_curve("AF_INSTANT_ANCHORS", field_test.anchor_polylines(anchors),
                                   collection, values["anchor"], 0.0035)
    return {"surface": obj, "wire": wire, "anchors": anchor}


def render_specs():
    visible = {"surface", "wire", "anchors"}
    return (("front", visible, (0.0, -8.0, 1.25)),
            ("threequarter", visible, (4.6, -7.0, 2.8)),
            ("side", visible, (7.5, 0.0, 1.25)),
            ("back", {"surface", "wire"}, (0.0, 8.0, 1.25)))


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
    labels = ("Instant Meshes + authored guides", "Field-aligned mesh — three-quarter",
              "Field-aligned mesh — side", "Field-aligned mesh — back")
    canvas = Image.new("RGB", (1440, 1440), (5, 8, 14))
    for index, (image, label) in enumerate(zip(images, labels)):
        field_test.paste_panel(canvas, image, label, index, ImageDraw)
    canvas.save(folder / "topology_instant_meshes_comparison.png")


def mesh_arrays(obj):
    vertices = np.asarray([vertex.co[:] for vertex in obj.data.vertices])
    faces = tuple(tuple(polygon.vertices) for polygon in obj.data.polygons)
    return vertices, faces


def edge_counts(faces):
    values = Counter()
    for face in faces:
        for first, second in zip(face, face[1:] + face[:1]):
            values[tuple(sorted((int(first), int(second))))] += 1
    return values


def symmetry_error(vertices):
    from scipy.spatial import cKDTree
    reflected = vertices.copy()
    reflected[:, 0] *= -1.0
    return float(cKDTree(vertices).query(reflected, workers=-1)[0].max())


def quad_aspects(vertices, faces):
    quads = np.asarray([face for face in faces if len(face) == 4], dtype=np.int32)
    points = vertices[quads]
    lengths = np.stack([np.linalg.norm(points[:, (i + 1) % 4] - points[:, i], axis=1)
                        for i in range(4)], axis=1)
    return lengths.max(axis=1) / np.maximum(lengths.min(axis=1), 1.0e-12)


def metrics(obj):
    vertices, faces = mesh_arrays(obj)
    counts = edge_counts(faces)
    aspects = quad_aspects(vertices, faces)
    arities = Counter(map(len, faces))
    return {"vertices": len(vertices), "faces": len(faces), "face_arities": dict(arities),
            "boundary_edges": sum(value == 1 for value in counts.values()),
            "nonmanifold_edges": sum(value > 2 for value in counts.values()),
            "symmetry_error": symmetry_error(vertices),
            "aspect_p95": float(np.quantile(aspects, 0.95)),
            "aspect_max": float(aspects.max())}


def build(args):
    _root, skin = guide_test.scene_inputs()
    anchors = () if args.ignore_guides else field_test.anchor_objects()
    collection = guide_test.make_collection("AF_TOPOLOGY_INSTANT_MESHES_TEST")
    work = global_test.smooth_proxy(skin, args.target_faces, collection)
    vertices, faces = remesh_arrays(work, anchors, args.vendor, args.target_vertices)
    raw = create_mesh(vertices, faces, collection)
    return skin, anchors, collection, stitched_mesh(raw, anchors, collection)


def finish(args, data):
    _skin, anchors, collection, obj = data
    values = metrics(obj)
    visuals = create_visuals(obj, anchors, collection)
    render_all(prepare_render(visuals), visuals, args.render_dir)
    Path(args.render_dir, "metrics.json").write_text(json.dumps(values, indent=2), encoding="utf-8")
    obj["af_topology_instant_test"] = json.dumps(values, sort_keys=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, copy=True)
    print("AF_TOPOLOGY_INSTANT", json.dumps(values, sort_keys=True), flush=True)


def main():
    args = parse_args()
    guide_test.ensure_runtime()
    finish(args, build(args))


if __name__ == "__main__":
    main()
