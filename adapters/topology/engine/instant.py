import argparse
import json
import subprocess
import sys
try:
    from ....core.native_platform import python_executable
except ImportError:
    from core.native_platform import python_executable
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import annuli as annulus_test
from . import field as field_test
from . import layout as global_test
from . import guides as guide_test
from . import cube as cube_test


@dataclass(frozen=True)
class SymmetryPlane:
    origin: np.ndarray
    normal: np.ndarray


SPARSE_COUNT_DIFFERENCE = 12
SPARSE_COUNT_RATIO = 1.5
SPARSE_P95_LIMIT = 4.0
SPARSE_MAX_LIMIT = 12.0
GUIDE_CUT_SCALE = 1.08


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--target-vertices", type=int, default=4200)
    parser.add_argument("--target-faces", type=int, default=64000)
    parser.add_argument("--ignore-guides", action="store_true")
    parser.add_argument("--stress-variant", default="")
    parser.add_argument("--symmetry-origin", nargs=3, type=float, default=(0.0, 0.0, 0.0))
    parser.add_argument("--symmetry-normal", nargs=3, type=float, default=(1.0, 0.0, 0.0))
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def symmetry_plane(args):
    origin = np.asarray(args.symmetry_origin, dtype=np.float64)
    normal = np.asarray(args.symmetry_normal, dtype=np.float64)
    length = float(np.linalg.norm(normal))
    if not np.isfinite(origin).all() or not np.isfinite(normal).all() or length < 1.0e-12:
        raise ValueError("Symmetry plane requires a finite origin and non-zero normal.")
    return SymmetryPlane(origin, normal / length)


def remesh_arrays(work, anchors, vendor, count, plane):
    bisect_left_half(work, plane)
    vertices, faces, _normals = guide_test.mesh_arrays(work)
    faces = cut_guide_holes(vertices, faces, anchors, plane)
    with tempfile.TemporaryDirectory(prefix="af_instant_") as folder:
        input_path, output_path = write_worker_input(folder, vertices, faces)
        run_worker(input_path, output_path, vendor, count)
        with np.load(output_path, allow_pickle=False) as values:
            return mirrored_output(
                values["vertices"].copy(), values["faces"].copy(), anchors, plane)


def local_plane(work, plane):
    origin = work.matrix_world.inverted() @ Vector(plane.origin)
    normal = work.matrix_world.to_3x3().transposed() @ Vector(plane.normal)
    return origin, normal.normalized()


def bisect_left_half(work, plane):
    mesh = bmesh.new()
    mesh.from_mesh(work.data)
    geometry = tuple(mesh.verts) + tuple(mesh.edges) + tuple(mesh.faces)
    origin, normal = local_plane(work, plane)
    bmesh.ops.bisect_plane(mesh, geom=geometry, plane_co=origin,
                           plane_no=normal, clear_outer=True,
                           clear_inner=False, use_snap_center=True)
    bmesh.ops.triangulate(mesh, faces=tuple(mesh.faces))
    mesh.to_mesh(work.data)
    mesh.free()


def mirrored_output(vertices, faces, anchors, plane):
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    snap_symmetry_boundary(vertices, faces, diagonal, plane)
    faces = exterior_half_faces(vertices, faces, plane, 1.0e-6 * diagonal)
    mirrored = reflect_points(vertices, plane)
    parts = [(vertices, faces), (mirrored, faces[:, ::-1])]
    hybrid = cube_test.welded_hybrid(parts, 1.0e-6 * diagonal)
    return hybrid.vertices, hybrid.faces


def exterior_half_faces(vertices, faces, plane, tolerance):
    """Discard cut-plane caps that would become internal faces after mirroring."""
    distances = np.abs(signed_distances(vertices, plane))
    return faces[np.max(distances[faces], axis=1) > tolerance]


def signed_distances(points, plane):
    return (np.asarray(points) - plane.origin) @ plane.normal


def reflect_points(points, plane):
    values = np.asarray(points)
    distances = signed_distances(values, plane)
    return values - (2.0 * distances[:, None] * plane.normal)


def snap_symmetry_boundary(vertices, faces, diagonal, plane):
    boundary = np.unique(boundary_edges(faces))
    distances = signed_distances(vertices, plane)
    near = boundary[np.abs(distances[boundary]) < 0.02 * diagonal]
    vertices[near] -= distances[near, None] * plane.normal
    outside = np.maximum(signed_distances(vertices, plane), 0.0)
    vertices[:] -= outside[:, None] * plane.normal


def fill_unmatched_boundaries(hybrid, anchors, plane):
    loops = cube_test.boundary_loops(boundary_edges(hybrid.faces))
    extras = unmatched_boundaries(loops, hybrid.vertices, anchors)
    mesh = hybrid_bmesh(hybrid)
    for loop in extras:
        fill_bmesh_loop(mesh, loop, plane)
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


def fill_bmesh_loop(mesh, loop, plane):
    first_ids, second_ids = mirrored_loop_chains(mesh, loop, plane)
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


def mirrored_loop_chains(mesh, loop, plane):
    fixed = [index for index, vertex in enumerate(loop)
             if abs(vertex_plane_distance(mesh.verts[int(vertex)], plane)) < 1.0e-8]
    if len(fixed) != 2:
        raise RuntimeError("Unmatched boundary is not a symmetry slit.")
    start, end = fixed
    first = loop[start:end + 1]
    second = tuple(reversed(loop[end:] + loop[:start + 1]))
    if chain_side(mesh, first, plane) > chain_side(mesh, second, plane):
        first, second = second, first
    return first, second


def vertex_plane_distance(vertex, plane):
    return float(signed_distances(np.asarray(vertex.co), plane))


def chain_side(mesh, chain, plane):
    points = np.asarray([mesh.verts[int(index)].co[:] for index in chain])
    return float(signed_distances(points, plane).mean())


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


def guide_face_mask(vertices, faces, ring, scale=1.0):
    center, first, second, normal = ring_frame(ring)
    polygon = local_points(ring, center, first, second) * scale
    centers = vertices[faces].mean(axis=1)
    local = local_points(centers, center, first, second)
    radius = np.linalg.norm(ring - center, axis=1).max()
    nearby = np.linalg.norm(centers - center, axis=1) < 1.8 * radius
    depth = np.abs((centers - center) @ normal) < 0.55 * radius
    inside = np.asarray([global_test.point_in_polygon(point, polygon) for point in local])
    return nearby & depth & inside


def cut_guide_holes(vertices, faces, anchors, plane):
    if not anchors:
        return faces
    diagonal = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1.0e-9)
    rings = tuple(global_test.outer_ring(anchor) for anchor in anchors)
    scales = tuple(guide_cut_scale(ring, plane, diagonal) for ring in rings)
    masks = [guide_face_mask(vertices, faces, ring, scale) for ring, scale in zip(rings, scales)]
    removed = np.logical_or.reduce(masks)
    return faces[~removed]


def guide_cut_scale(ring, plane, diagonal):
    return 1.0 if loop_is_centered(ring, plane, diagonal) else GUIDE_CUT_SCALE


def write_worker_input(folder, vertices, faces):
    input_path, output_path = Path(folder, "input.npz"), Path(folder, "output.npz")
    np.savez(input_path, vertices=vertices.astype(np.float32), faces=faces.astype(np.int32))
    return input_path, output_path


def run_worker(input_path, output_path, vendor, count):
    python = python_executable()
    worker = Path(__file__).resolve().parents[3] / "workers" / "topology_instant_worker.py"
    command = [str(python), str(worker), "--input", str(input_path), "--output", str(output_path),
               "--vendor", str(vendor), "--target-vertices", str(count)]
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


def guide_transitions(vertices, faces, anchors, plane):
    loops = cube_test.boundary_loops(boundary_edges(faces))
    pairs = cube_test.matched_boundaries(loops, vertices, anchors)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    values = [make_transition(anchor.name, pair, diagonal, plane)
              for anchor, pair in zip(anchors, pairs)]
    return mirror_paired_transitions(values, diagonal, plane)


def interior_transitions(vertices, faces, anchors, plane):
    loops = cube_test.boundary_loops(boundary_edges(faces))
    extras = unmatched_boundaries(loops, vertices, anchors)
    diagonal = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0)))
    values = [inner_transition(loop, vertices, anchors, diagonal, plane) for loop in extras]
    return mirror_paired_transitions(values, diagonal, plane)


def inner_transition(loop, vertices, anchors, diagonal, plane):
    boundary = vertices[np.asarray(loop)]
    anchor = min(anchors, key=lambda item: np.linalg.norm(
        inner_ring(item).mean(axis=0) - boundary.mean(axis=0)))
    return make_transition(f"{anchor.name}_INNER", (boundary, inner_ring(anchor)), diagonal, plane)


def inner_ring(anchor):
    rings = cube_test.ordered_anchor_rings(anchor)
    return min(rings, key=global_test.ring_perimeter)


def make_transition(name, pair, diagonal, plane):
    boundary, ring = pair
    centered = tuple(loop_is_centered(loop, plane, diagonal) for loop in pair)
    if centered[0] != centered[1]:
        raise RuntimeError(f"Topology guide '{name}' was matched to the wrong symmetry side.")
    if not centered[0]:
        return side_transition(name, boundary, ring)
    first = cube_test.canonical_loop(boundary)
    second = cube_test.align_loop(first, ring)
    return centered_transition(name, first, second, plane)


def centered_transition(name, first, second, plane):
    loops = centered_transition_loops(first, second, plane)
    parts = tuple(centered_transition_strip(a, b, plane) for a, b in zip(loops, loops[1:]))
    diagonal = max(float(np.linalg.norm(np.ptp(np.vstack((first, second)), axis=0))), 1.0e-9)
    merged = cube_test.welded_hybrid(parts, 1.0e-7 * diagonal)
    details = transition_details("CENTERED", name, first, second, merged.vertices, merged.faces)
    return cube_test.Transition(name, merged.vertices, merged.faces, details)


def centered_transition_loops(first, second, plane):
    stages = transition_stage_count(len(first), len(second))
    values = [first]
    for index in range(1, stages):
        alpha = index / stages
        values.append(blended_transition_loop(first, second, alpha, plane))
    return tuple((*values, second))


def transition_stage_count(first, second):
    ratio = max(first, second) / max(min(first, second), 1)
    return max(1, int(np.ceil(np.log(ratio) / np.log(1.5))))


def blended_transition_loop(first, second, alpha, plane):
    estimate = len(first) * ((len(second) / len(first)) ** alpha)
    count = max(4, 2 * int(round(estimate / 2.0)))
    a = cube_test.loop_samples(first, count)
    b = cube_test.loop_samples(second, count)
    points = ((1.0 - alpha) * a) + (alpha * b)
    return enforce_transition_symmetry(points, plane)


def enforce_transition_symmetry(points, plane):
    reflected = reflect_points(points, plane)
    distances = np.linalg.norm(points[None, :, :] - reflected[:, None, :], axis=2)
    mapping = np.argmin(distances, axis=1)
    partners = reflect_points(points[mapping], plane)
    return 0.5 * (points + partners)


def centered_transition_strip(first, second, plane):
    local = tuple(plane_coordinates(loop, plane) for loop in (first, second))
    faces = equal_transition_faces(len(first)) if len(first) == len(second) else (
        cube_test.centered_transition_faces(*local))
    cube_test.validate_transition_boundary(faces, len(first), len(second))
    return np.vstack((first, second)), faces


def loop_is_centered(points, plane, diagonal):
    if plane is None:
        return False
    distance = abs(float(signed_distances(points.mean(axis=0), plane)))
    return distance <= 1.0e-5 * diagonal


def plane_coordinates(points, plane):
    reference = np.asarray((0.0, 0.0, 1.0))
    if abs(float(np.dot(reference, plane.normal))) > 0.9:
        reference = np.asarray((0.0, 1.0, 0.0))
    vertical = reference - (np.dot(reference, plane.normal) * plane.normal)
    vertical /= max(float(np.linalg.norm(vertical)), 1.0e-12)
    tangent = np.cross(vertical, plane.normal)
    relative = np.asarray(points) - plane.origin
    return np.column_stack((relative @ plane.normal, relative @ tangent, relative @ vertical))


def equal_transition_faces(count):
    return np.asarray([(index, (index + 1) % count,
                        count + ((index + 1) % count), count + index)
                       for index in range(count)], dtype=np.int32)


def side_transition(name, boundary, ring):
    first = cube_test.canonical_loop(boundary)
    second = cube_test.align_loop(first, ring)
    reason = sparse_rejection(first, second)
    if reason == "parity mismatch":
        raise RuntimeError(f"Topology guide '{name}' has incompatible boundary parity.")
    if reason:
        return staged_side_transition(name, first, second, reason)
    result = best_sparse_transition(name, first, second)
    if sparse_quality_ok(result.diagnostics):
        return result
    return staged_side_transition(name, first, second, "sparse quality limits exceeded")


def sparse_rejection(first, second):
    smaller, larger = sorted((len(first), len(second)))
    if smaller < 4:
        return "fewer than four boundary vertices"
    if (larger - smaller) % 2:
        return "parity mismatch"
    if larger - smaller > SPARSE_COUNT_DIFFERENCE:
        return "boundary count difference exceeds 12"
    return "boundary count ratio exceeds 1.5" if larger / smaller > SPARSE_COUNT_RATIO else ""


def seam_shifts(count):
    radius = min(3, max(1, count // 12))
    values = [0]
    for shift in range(1, radius + 1):
        values.extend((-shift, shift))
    return tuple(values)


def sparse_candidate(name, first, second, shift, total):
    ring = np.roll(second, shift, axis=0)
    vertices = np.vstack((first, ring))
    faces = cube_test.regular_transition_faces(first, ring)
    validate_sparse_arrays(name, vertices, faces)
    cube_test.validate_transition_boundary(faces, len(first), len(ring))
    details = transition_details("SPARSE", name, first, ring, vertices, faces)
    details.update(candidate_count=total, selected_seam_shift=shift, fallback_reason="")
    return cube_test.Transition(name, vertices, faces, details)


def validate_sparse_arrays(name, vertices, faces):
    valid_faces = faces.ndim == 2 and faces.shape[1] == 4 and len(faces) > 0
    if not np.isfinite(vertices).all() or not valid_faces:
        raise RuntimeError(f"Topology guide '{name}' produced an invalid sparse transition.")


def best_sparse_transition(name, first, second):
    shifts = seam_shifts(min(len(first), len(second)))
    values = tuple(sparse_candidate(name, first, second, shift, len(shifts)) for shift in shifts)
    return min(values, key=sparse_score)


def sparse_score(item):
    values = item.diagnostics
    shift = int(values["selected_seam_shift"])
    return (values["local_intersections"], values["aspect_p95"],
            values["aspect_max"], abs(shift), shift)


def sparse_quality_ok(values):
    return bool(values["local_intersections"] == 0
                and values["aspect_p95"] <= SPARSE_P95_LIMIT
                and values["aspect_max"] <= SPARSE_MAX_LIMIT)


def transition_details(mode, name, first, second, vertices, faces):
    aspects = quad_aspects(vertices, faces)
    return {"guide_name": name, "mode": mode, "boundary_count": len(first),
            "annulus_count": len(second), "candidate_count": 1,
            "selected_seam_shift": 0, "local_intersections": self_intersection_count(vertices, faces),
            "aspect_p95": float(np.quantile(aspects, 0.95)),
            "aspect_max": float(aspects.max()), "fallback_reason": ""}


def staged_side_transition(name, first, second, reason):
    middle = intermediate_ring(first, second)
    outer = cube_test.transition_mesh(name, first, middle)
    inner = cube_test.transition_mesh(name, middle, second)
    diagonal = float(np.linalg.norm(first.max(axis=0) - first.min(axis=0)))
    merged = cube_test.welded_hybrid(
        ((outer.vertices, outer.faces), (inner.vertices, inner.faces)), 1.0e-7 * diagonal)
    details = transition_details("STAGED", name, first, second, merged.vertices, merged.faces)
    details["fallback_reason"] = reason
    return cube_test.Transition(name, merged.vertices, merged.faces, details)


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


def reflected_center(item, plane):
    return reflect_points(transition_center(item)[None, :], plane)[0]


def mirror_paired_transitions(values, diagonal, plane):
    if plane is None:
        return tuple(values)
    pending = {index for index, item in enumerate(values)
               if signed_distances(transition_center(item), plane) > 1.0e-5 * diagonal}
    for index, item in enumerate(values):
        if signed_distances(transition_center(item), plane) < -1.0e-5 * diagonal:
            mirror_one_transition(values, index, pending, diagonal, plane)
    return tuple(values)


def mirror_one_transition(values, source, pending, diagonal, plane):
    if not pending:
        return
    target = min(pending, key=lambda index: np.linalg.norm(
        transition_center(values[index]) - reflected_center(values[source], plane)))
    error = np.linalg.norm(transition_center(values[target]) - reflected_center(values[source], plane))
    if error < 0.02 * diagonal:
        values[target] = mirrored_transition(values[source], values[target], plane)
        pending.remove(target)


def mirrored_transition(source, target, plane):
    from scipy.spatial import cKDTree
    points = reflect_points(source.vertices, plane)
    distances, indices = cKDTree(target.vertices).query(points, workers=-1)
    if float(distances.max()) > 1.0e-4:
        raise RuntimeError("Transition pair is not symmetric across the requested plane.")
    details = dict(source.diagnostics); details["guide_name"] = target.name
    return cube_test.Transition(target.name, target.vertices, indices[source.faces][:, ::-1], details)


def stitched_mesh(obj, anchors, collection, plane):
    vertices, faces = object_quad_arrays(obj)
    transitions = guide_transitions(vertices, faces, anchors, plane)
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


def symmetry_error(vertices, plane):
    from scipy.spatial import cKDTree
    reflected = reflect_points(vertices, plane)
    return float(cKDTree(vertices).query(reflected, workers=-1)[0].max())


def edge_symmetry_error(vertices, counts, plane):
    from scipy.spatial import cKDTree
    edges = np.asarray(tuple(counts), dtype=np.int32)
    centers = vertices[edges].mean(axis=1)
    reflected = reflect_points(centers, plane)
    return float(cKDTree(centers).query(reflected, workers=-1)[0].max())


def boundary_loop_counts(counts):
    edges = np.asarray([edge for edge, value in counts.items() if value == 1],
                       dtype=np.int32)
    if not len(edges):
        return []
    return sorted(len(loop) for loop in cube_test.boundary_loops(edges))


def component_count(vertex_count, counts):
    adjacency = [set() for _index in range(vertex_count)]
    for first, second in counts:
        adjacency[first].add(second)
        adjacency[second].add(first)
    pending, result = set(range(vertex_count)), 0
    while pending:
        stack, result = [pending.pop()], result + 1
        while stack:
            linked = adjacency[stack.pop()].intersection(pending)
            pending.difference_update(linked)
            stack.extend(linked)
    return result


def degenerate_face_count(vertices, faces):
    quads = np.asarray(faces, dtype=np.int32)
    points = vertices[quads]
    first = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    second = np.cross(points[:, 2] - points[:, 0], points[:, 3] - points[:, 0])
    areas = 0.5 * (np.linalg.norm(first, axis=1) + np.linalg.norm(second, axis=1))
    repeated = np.asarray([len(set(face)) < len(face) for face in faces])
    return int(np.count_nonzero((areas < 1.0e-12) | repeated))


def self_intersection_count(vertices, faces):
    bvh = BVHTree.FromPolygons(vertices.tolist(), faces, all_triangles=False)
    pairs = bvh.overlap(bvh)
    return sum(first < second and not set(faces[first]).intersection(faces[second])
               for first, second in pairs)


def guide_preservation(vertices, faces, anchors):
    from scipy.spatial import cKDTree
    tree, face_sets = cKDTree(vertices), {frozenset(face) for face in faces}
    return {anchor.name: preserved_anchor(anchor, tree, face_sets) for anchor in anchors}


def preserved_anchor(anchor, tree, face_sets):
    points = field_test.object_world_vertices(anchor)
    distances, indices = tree.query(points, workers=-1)
    kept = sum(frozenset(int(indices[index]) for index in polygon.vertices) in face_sets
               for polygon in anchor.data.polygons)
    return {"vertex_error": float(distances.max()), "faces": int(kept),
            "expected_faces": len(anchor.data.polygons)}


def valence_metrics(vertex_count, counts):
    values = np.zeros(vertex_count, dtype=np.int32)
    for first, second in counts:
        values[first] += 1
        values[second] += 1
    unique, frequencies = np.unique(values, return_counts=True)
    return {"maximum": int(values.max()),
            "counts": {str(int(key)): int(value)
                       for key, value in zip(unique, frequencies)}}


def quad_aspects(vertices, faces):
    quads = np.asarray([face for face in faces if len(face) == 4], dtype=np.int32)
    points = vertices[quads]
    lengths = np.stack([np.linalg.norm(points[:, (i + 1) % 4] - points[:, i], axis=1)
                        for i in range(4)], axis=1)
    return lengths.max(axis=1) / np.maximum(lengths.min(axis=1), 1.0e-12)


def metrics(obj, anchors, plane):
    vertices, faces = mesh_arrays(obj)
    counts = edge_counts(faces)
    values = topology_metrics(vertices, faces, counts)
    values.update(quality_metrics(vertices, faces, counts, plane))
    values["guides"] = guide_preservation(vertices, faces, anchors)
    values["symmetry_plane"] = {
        "origin": plane.origin.tolist(), "normal": plane.normal.tolist()}
    return values


def topology_metrics(vertices, faces, counts):
    return {"vertices": len(vertices), "faces": len(faces),
            "face_arities": dict(Counter(map(len, faces))),
            "boundary_edges": sum(value == 1 for value in counts.values()),
            "nonmanifold_edges": sum(value > 2 for value in counts.values()),
            "boundary_loops": boundary_loop_counts(counts),
            "euler_characteristic": len(vertices) - len(counts) + len(faces),
            "components": component_count(len(vertices), counts),
            "finite": bool(np.isfinite(vertices).all()),
            "degenerate_faces": degenerate_face_count(vertices, faces),
            "self_intersections": self_intersection_count(vertices, faces)}


def quality_metrics(vertices, faces, counts, plane):
    aspects = quad_aspects(vertices, faces)
    return {"symmetry_error": symmetry_error(vertices, plane),
            "edge_symmetry_error": edge_symmetry_error(vertices, counts, plane),
            "valence": valence_metrics(len(vertices), counts),
            "aspect_p95": float(np.quantile(aspects, 0.95)),
            "aspect_max": float(aspects.max())}


def build(args):
    _root, skin = guide_test.scene_inputs()
    apply_stress_variant(args.stress_variant)
    plane = symmetry_plane(args)
    anchors = () if args.ignore_guides else field_test.anchor_objects()
    collection = guide_test.make_collection("AF_TOPOLOGY_INSTANT_MESHES_TEST")
    work = global_test.smooth_proxy(skin, args.target_faces, collection)
    vertices, faces = remesh_arrays(work, anchors, args.vendor, args.target_vertices, plane)
    raw = create_mesh(vertices, faces, collection)
    return skin, anchors, collection, stitched_mesh(raw, anchors, collection, plane), plane


def apply_stress_variant(name):
    if not name:
        return
    import prototype_topology_stress_variants as stress
    stress.apply_variant(name)


def finish(args, data):
    _skin, anchors, collection, obj, plane = data
    values = metrics(obj, anchors, plane)
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
