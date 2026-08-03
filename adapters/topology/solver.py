import tempfile
from pathlib import Path

import bpy
import bmesh
import numpy as np
from scipy.spatial import cKDTree

from .engine import annuli, cube, guides, instant, layout
from .density_runtime import budget_statistics, budget_warnings, build_density, has_adaptive_density, sample_density
from .adaptive_refine import base_quad_target, refine_to_density

try:
    from ...core.topology.constants import GUIDE_ROWS, REGION_AUTO, REGION_GUIDE, REGION_TRANSITION
    from ...core.topology.density import corrected_target, internal_target, needs_correction, proxy_face_count
    from ...core.topology.model import TopologyResult
    from ...core.topology.status import check_cancelled
    from ...core.topology.validation import validate_topology
except ImportError:
    from core.topology.constants import GUIDE_ROWS, REGION_AUTO, REGION_GUIDE, REGION_TRANSITION
    from core.topology.density import corrected_target, internal_target, needs_correction, proxy_face_count
    from core.topology.model import TopologyResult
    from core.topology.status import check_cancelled
    from core.topology.validation import validate_topology


def solve_capture(capture, vendor, status=None, cancelled=None):
    update = status or (lambda *_args: None)
    skin, collection = _skin_object(capture)
    update("Guides", 0.15, "Projecting closed topology guides.")
    anchors, guide_map, warnings = _anchors(capture, skin, collection)
    check_cancelled(cancelled)
    update("Density", 0.32, "Resolving hierarchical SCP topology density.")
    density = build_density(capture)
    target = _initial_target(capture, density, anchors)
    result = _run_mesh(capture, skin, anchors, collection, vendor, target, density, update)
    if needs_correction(len(result[1]), capture.settings.target_quad_count):
        target = corrected_target(target, len(result[1]), capture.settings.target_quad_count)
        result = _run_mesh(capture, skin, anchors, collection, vendor, target, density, update)
    check_cancelled(cancelled)
    return _finish(capture, result, anchors, guide_map, warnings, target, density, update)


def _initial_target(capture, density, anchors):
    reserved = _reserved_quads(anchors)
    base = base_quad_target(capture, density, reserved) if has_adaptive_density(capture) else capture.settings.target_quad_count
    return internal_target(base, reserved)


def _skin_object(capture):
    collection = bpy.data.collections.new("AF_TOPOLOGY_WORK")
    bpy.context.scene.collection.children.link(collection)
    mesh = bpy.data.meshes.new("AF_TOPOLOGY_SOURCE")
    mesh.from_pydata(capture.vertices.tolist(), [], capture.triangles.tolist())
    skin = bpy.data.objects.new("AF_TOPOLOGY_SOURCE", mesh)
    collection.objects.link(skin)
    skin["af_draft_skin"] = True
    return skin, collection


def _engine_guides(capture):
    return tuple(guides.Guide(item.object_name, item.fiber_id, True, item.points)
                 for item in capture.guides)


def _engine_plane(capture):
    if capture.plane is None:
        return None
    return annuli.SymmetryPlane(np.asarray(capture.plane.origin), np.asarray(capture.plane.normal))


def _anchors(capture, skin, collection):
    vertices, faces, _normals = guides.mesh_arrays(skin)
    bvh, diagonal = guides.surface_bvh(vertices, faces), float(np.linalg.norm(np.ptp(vertices, axis=0)))
    graph, tree = annuli.surface_graph(vertices, faces), cKDTree(vertices)
    loops = annuli.surface_loops(_engine_guides(capture), bvh, diagonal, graph, tree,
                                  vertices, _engine_plane(capture))
    pairs, unpaired = _compatible_pairs(loops)
    patches = annuli.build_patches(pairs, bvh, diagonal, GUIDE_ROWS, _engine_plane(capture))
    objects = annuli.create_patch_objects(patches, collection, None)
    mapping = [{"guide_index": i, "sources": list(patch.source_names)}
               for i, patch in enumerate(patches)]
    warnings = [f"Ignored unpaired topology loop: {item.name}" for item in unpaired]
    return objects, mapping, warnings


def _compatible_pairs(loops):
    pending, pairs, rejected = list(loops), [], []
    while pending:
        first = pending.pop(0)
        candidates = [(i, item) for i, item in enumerate(pending) if _nested(first, item)]
        if not candidates:
            rejected.append(first); continue
        index, second = min(candidates, key=lambda item: annuli.pair_score(first, item[1]))
        pending.pop(index)
        pairs.append(tuple(sorted((first, second), key=lambda loop: -loop.perimeter)))
    return tuple(pairs), tuple(rejected)


def _nested(first, second):
    outer, inner = sorted((first, second), key=lambda item: -item.perimeter)
    ratio = inner.perimeter / max(outer.perimeter, 1e-9)
    center, axis, tangent, normal = instant.ring_frame(outer.points)
    radius = np.linalg.norm(outer.points - center, axis=1).max()
    planar = instant.local_points(outer.points, center, axis, tangent)
    inside = layout.point_in_polygon(instant.local_points(inner.center[None], center, axis, tangent)[0], planar)
    depth = abs(float(np.dot(inner.center - center, normal)))
    return bool(0.2 <= ratio <= 0.95 and inside and depth <= 0.25 * radius)


def _reserved_quads(anchors):
    return sum(len(obj.data.polygons) for obj in anchors) * 3


def _run_mesh(capture, skin, anchors, collection, vendor, target, density, update):
    update("Remeshing", 0.48, f"Solving field-aligned quads (target {target}).")
    faces = proxy_face_count(len(capture.triangles), capture.settings.target_quad_count)
    work = layout.smooth_proxy(skin, faces, collection)
    if capture.plane is None:
        vertices, quads = _full_remesh(work, anchors, vendor, target)
    else:
        plane = instant.SymmetryPlane(capture.plane.origin, capture.plane.normal)
        vertices, quads = instant.remesh_arrays(work, anchors, vendor, target, plane)
    if has_adaptive_density(capture):
        labels = np.full(len(quads), REGION_AUTO); indices = np.full(len(quads), -1)
        vertices, quads, _labels, _indices = refine_to_density(
            capture, (vertices, quads, labels, indices), density)
    update("Stitching", 0.76, "Stitching immutable guide annuli.")
    return _assemble(vertices, quads, anchors, capture.plane)


def _full_remesh(work, anchors, vendor, target):
    vertices, faces, _normals = guides.mesh_arrays(work)
    faces = instant.cut_guide_holes(vertices, faces, anchors)
    with tempfile.TemporaryDirectory(prefix="af_topology_") as folder:
        source, output = instant.write_worker_input(folder, vertices, faces)
        instant.run_worker(source, output, vendor, target)
        with np.load(output, allow_pickle=False) as data:
            return data["vertices"].copy(), data["faces"].copy()


def _assemble(vertices, faces, anchors, plane):
    values = np.asarray(faces, dtype=np.int32)
    transitions = instant.guide_transitions(vertices, values, anchors, _instant_plane(plane))
    parts = [(np.asarray(vertices), values, REGION_AUTO, -1)]
    parts.extend((item.vertices, item.faces, REGION_TRANSITION, i)
                 for i, item in enumerate(transitions))
    parts.extend((*cube.anchor_mesh(anchor), REGION_GUIDE, i)
                 for i, anchor in enumerate(anchors))
    diagonal = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1e-9)
    return _weld_labeled(parts, 1e-6 * diagonal)


def _instant_plane(plane):
    if plane is None:
        return None
    return instant.SymmetryPlane(np.asarray(plane.origin), np.asarray(plane.normal))


def _weld_labeled(parts, tolerance):
    vertices, faces, regions, indices = _combined_labeled(parts)
    keys = np.round(vertices / tolerance).astype(np.int64)
    _unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    remapped = inverse[faces]
    valid = np.asarray([len(set(map(int, face))) == 4 for face in remapped])
    used = np.unique(remapped[valid])
    compact = np.full(len(first), -1, dtype=np.int32); compact[used] = np.arange(len(used))
    points, faces = vertices[first][used], compact[remapped[valid]]
    return points, _orient_faces(points, faces), regions[valid], indices[valid]


def _orient_faces(vertices, faces):
    mesh = bmesh.new()
    for point in vertices:
        mesh.verts.new(point)
    mesh.verts.ensure_lookup_table()
    for face in faces:
        mesh.faces.new([mesh.verts[int(index)] for index in face])
    mesh.faces.index_update(); bmesh.ops.recalc_face_normals(mesh, faces=tuple(mesh.faces))
    values = np.asarray([tuple(vertex.index for vertex in face.verts)
                         for face in sorted(mesh.faces, key=lambda item: item.index)], dtype=np.int32)
    mesh.free()
    return values


def _combined_labeled(parts):
    vertices, faces, regions, indices, offset = [], [], [], [], 0
    for points, polygons, region, guide_index in parts:
        vertices.append(points); faces.append(np.asarray(polygons) + offset)
        regions.extend([region] * len(polygons)); indices.extend([guide_index] * len(polygons))
        offset += len(points)
    return np.vstack(vertices), np.vstack(faces), np.asarray(regions), np.asarray(indices)


def _finish(capture, result, anchors, guide_map, warnings, target, density, update):
    update("Validation", 0.9, "Validating topology and guide preservation.")
    vertices, faces, regions, indices = result
    owners, lengths = sample_density(capture, density[0], density[1], vertices)
    metrics = _metrics(capture, vertices, faces, regions, anchors)
    report = validate_topology(vertices, faces, metrics)
    budgets = budget_statistics(capture, owners, faces, density[2])
    all_warnings = _result_warnings(capture, warnings, density, metrics, budgets)
    stats = _result_stats(capture, metrics, target, guide_map, all_warnings,
                          budgets)
    if not report.valid:
        raise RuntimeError(report.message)
    return TopologyResult(vertices, faces, regions, indices, stats, report, owners, lengths)


def _result_warnings(capture, warnings, density, metrics, budgets):
    values = list(capture.warnings) + list(warnings) + list(density[3])
    values.extend(budget_warnings(budgets))
    if metrics["self_intersections"]:
        values.append(f"Detected {metrics['self_intersections']} local self-intersections.")
    return values


def _result_stats(capture, metrics, target, guide_map, warnings, budgets):
    return dict(metrics, input_hash=capture.input_hash, internal_target=target,
                requested_quads=capture.settings.target_quad_count,
                guide_map=guide_map, warnings=warnings,
                adaptive_density=has_adaptive_density(capture),
                density_backend=_density_backend(capture), topology_budgets=budgets,
                owner_map={item.scp_index: item.scp_id for item in capture.density_rules})


def _density_backend(capture):
    return "CONFORMING_QUAD_REFINEMENT" if has_adaptive_density(capture) else "UNIFORM_INSTANT_MESHES"


def _metrics(capture, vertices, faces, regions, anchors):
    counts = instant.edge_counts(tuple(map(tuple, faces)))
    loops = instant.boundary_loop_counts(counts)
    diagonal = max(float(np.linalg.norm(capture.upper - capture.lower)), 1e-9)
    fidelity = _fidelity(vertices, capture)
    symmetry = 0.0 if capture.plane is None else instant.symmetry_error(vertices, _instant_plane(capture.plane))
    guide_faces = sum(len(obj.data.polygons) for obj in anchors)
    return {"vertices": len(vertices), "faces": len(faces), "boundary_loops": loops,
            "boundary_match": len(loops) in {len(anchors), len(anchors) + 1},
            "guide_preserved": int(np.count_nonzero(regions == REGION_GUIDE)) == guide_faces,
            "symmetry_error": symmetry, "symmetry_ok": symmetry <= 1e-6 * diagonal,
            "fidelity_p95": fidelity, "fidelity_ok": fidelity <= 0.005 * diagonal,
            "self_intersections": instant.self_intersection_count(vertices, tuple(map(tuple, faces))),
            "valence": instant.valence_metrics(len(vertices), counts)}


def _fidelity(vertices, capture):
    bvh = guides.surface_bvh(capture.vertices, capture.triangles)
    distances = [np.linalg.norm(np.asarray(guides._nearest(bvh, point)[0]) - point)
                 for point in vertices]
    return float(np.quantile(distances, 0.95))
