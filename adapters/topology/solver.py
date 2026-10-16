import tempfile
from dataclasses import asdict
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
    from ...core.topology.bindings import build_topology_guide_binding, build_topology_skin_binding
    from ...core.topology.density import corrected_target, internal_target, needs_correction, proxy_face_count
    from ...core.topology.model import TopologyGuide, TopologyResult
    from ...core.topology.status import check_cancelled
    from ...core.topology.validation import validate_topology
    from ...core.warm_start.signatures import guide_layout_signature, structural_signature
    from ...core.warm_start.invalidation import guide_pairing_signature, settings_signature
except ImportError:
    from core.topology.constants import GUIDE_ROWS, REGION_AUTO, REGION_GUIDE, REGION_TRANSITION
    from core.topology.bindings import build_topology_guide_binding, build_topology_skin_binding
    from core.topology.density import corrected_target, internal_target, needs_correction, proxy_face_count
    from core.topology.model import TopologyGuide, TopologyResult
    from core.topology.status import check_cancelled
    from core.topology.validation import validate_topology
    from core.warm_start.signatures import guide_layout_signature, structural_signature
    from core.warm_start.invalidation import guide_pairing_signature, settings_signature


def solve_capture(capture, vendor, status=None, cancelled=None):
    update = status or (lambda *_args: None)
    skin, collection = _skin_object(capture)
    update("Guides", 0.15, "Projecting closed topology guides.")
    anchors, guide_map, warnings = _anchors(capture, skin, collection)
    check_cancelled(cancelled)
    update("Density", 0.32, "Resolving hierarchical SCP topology density.")
    density = build_density(capture)
    target = _initial_target(capture, density, anchors)
    result = _run_mesh(capture, skin, anchors, collection, vendor, target, density, update, cancelled)
    if capture.settings.backend == "INSTANT" and needs_correction(len(result[1]), capture.settings.target_quad_count):
        target = corrected_target(target, len(result[1]), capture.settings.target_quad_count)
        result = _run_mesh(capture, skin, anchors, collection, vendor, target, density, update, cancelled)
    check_cancelled(cancelled)
    return _finish(capture, result, anchors, guide_map, warnings, target, density, update)


def _initial_target(capture, density, anchors):
    reserved = _reserved_quads(anchors)
    base = base_quad_target(capture, density, reserved) if has_adaptive_density(capture) else capture.settings.target_quad_count
    return max(128, base-reserved) if capture.settings.backend == "QUADWILD" else internal_target(base, reserved)


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
    if not capture.guides: return (), [], []
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


def _run_mesh(capture, skin, anchors, collection, vendor, target, density, update, cancelled=None):
    update("Remeshing", 0.48, f"Solving field-aligned quads (target {target}).")
    faces = proxy_face_count(len(capture.triangles), capture.settings.target_quad_count)
    work = layout.smooth_proxy(skin, faces, collection)
    vertices, quads, backend = _remesh_backend(capture, work, anchors, vendor, target, cancelled, update)
    if has_adaptive_density(capture):
        labels = np.full(len(quads), REGION_AUTO); indices = np.full(len(quads), -1)
        vertices, quads, _labels, _indices = refine_to_density(
            capture, (vertices, quads, labels, indices), density)
    update("Stitching", 0.76, "Stitching immutable guide annuli.")
    return (*_assemble(vertices, quads, anchors, capture.plane, capture.settings.backend == "QUADWILD"), backend)


def _remesh_backend(capture, work, anchors, vendor, target, cancelled, update):
    if capture.settings.backend == "QUADWILD":
        from .quadwild import remesh
        return remesh(capture, work, anchors, target, cancelled, update)
    if capture.plane is None: vertices, faces = _full_remesh(work, anchors, vendor, target)
    else:
        plane = instant.SymmetryPlane(capture.plane.origin, capture.plane.normal)
        vertices, faces = instant.remesh_arrays(work, anchors, vendor, target, plane)
    return vertices, faces, {"backend": "INSTANT"}


def _full_remesh(work, anchors, vendor, target):
    vertices, faces, _normals = guides.mesh_arrays(work)
    faces = instant.cut_guide_holes(vertices, faces, anchors)
    with tempfile.TemporaryDirectory(prefix="af_topology_") as folder:
        source, output = instant.write_worker_input(folder, vertices, faces)
        instant.run_worker(source, output, vendor, target)
        with np.load(output, allow_pickle=False) as data:
            return data["vertices"].copy(), data["faces"].copy()


def _assemble(vertices, faces, anchors, plane, allow_unstitched=False):
    values = np.asarray(faces, dtype=np.int32)
    transitions, notices = _transitions(vertices, values, anchors, plane, allow_unstitched)
    parts = [(np.asarray(vertices), values, REGION_AUTO, -1)]
    parts.extend((item.vertices, item.faces, REGION_TRANSITION, i)
                 for i, item in enumerate(transitions))
    parts.extend((*cube.anchor_mesh(anchor), REGION_GUIDE, i)
                 for i, anchor in enumerate(anchors))
    diagonal = max(float(np.linalg.norm(np.ptp(vertices, axis=0))), 1e-9)
    mesh = _weld_labeled(parts, 1e-6 * diagonal)
    diagnostics = tuple(dict(item.diagnostics) for item in transitions) + notices
    return (*mesh, diagnostics)


def _instant_plane(plane):
    if plane is None:
        return None
    return instant.SymmetryPlane(np.asarray(plane.origin), np.asarray(plane.normal))


def _transitions(vertices, values, anchors, plane, allow_unstitched):
    try: return instant.guide_transitions(vertices, values, anchors, _instant_plane(plane)), ()
    except (ValueError, RuntimeError) as error:
        if not allow_unstitched: raise
        notice = dict(mode="UNSTITCHED", guide_name="Authored LOOP annuli", fallback_reason=str(error))
        return (), (notice,)


def _weld_labeled(parts, tolerance):
    vertices, faces, regions, indices = _combined_labeled(parts)
    keys = np.round(vertices / tolerance).astype(np.int64)
    _unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    remapped = inverse[faces]
    valid = _valid_weld_faces(remapped)
    used = np.unique(remapped[valid])
    compact = np.full(len(first), -1, dtype=np.int32); compact[used] = np.arange(len(used))
    points, faces = vertices[first][used], compact[remapped[valid]]
    return points, _orient_faces(points, faces), regions[valid], indices[valid]


def _valid_weld_faces(faces):
    distinct = np.asarray([len(set(map(int, face))) == 4 for face in faces])
    _values, reversed_indices = np.unique(np.sort(faces, axis=1)[::-1], axis=0, return_index=True)
    unique = np.zeros(len(faces), dtype=bool)
    unique[len(faces) - 1 - reversed_indices] = True
    return distinct & unique


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
    vertices, faces, regions, indices, transitions = result[:5]
    owners, lengths = sample_density(capture, density[0], density[1], vertices)
    metrics = _metrics(capture, vertices, faces, regions, anchors)
    report = validate_topology(vertices, faces, metrics)
    budgets = budget_statistics(capture, owners, faces, density[2])
    all_warnings = _result_warnings(capture, warnings, density, metrics, budgets, transitions) + result[5].get("warnings", [])
    stats = _result_stats(capture, metrics, target, guide_map, all_warnings,
                          budgets, density[4], transitions)
    stats.update(_warm_statistics(capture, vertices, faces, guide_map), backend_runtime=result[5], diagnostic_path=result[5].get("diagnostic", ""))
    stats["warnings"].extend(_require_valid_topology(capture, report, metrics) or ())
    bindings = _safe_bindings(capture, vertices, faces, regions, indices, anchors, stats)
    return _topology_result(result, stats, report, owners, lengths, bindings)


def _require_valid_topology(capture, report, metrics):
    if report.valid:
        return
    details = []
    if not report.fidelity_ok:
        limit = 0.005 * max(float(np.linalg.norm(capture.upper - capture.lower)), 1e-9)
        details.append(f"surface error P95 {metrics['fidelity_p95']:.4g} exceeds {limit:.4g}")
        if capture.plane is not None:
            details.append(f"check the selected {capture.settings.symmetry_mode} symmetry plane")
    if not report.valence_ok:
        details.append(f"maximum vertex valence {metrics['valence']['maximum']} exceeds 8")
    suffix = f" ({'; '.join(details)})" if details else ""
    return [report.message + suffix]


def _topology_result(result, stats, report, owners, lengths, bindings):
    vertices, faces, regions, indices, _transitions = result[:5]
    from ..mesh_issues import annotate
    from ..mesh_issues import check_result
    return annotate(check_result(TopologyResult(vertices, faces, regions, indices, stats, report,
                          owners, lengths, *bindings)), "topology")


def _result_bindings(capture, vertices, faces, regions, indices, anchors):
    skin = build_topology_skin_binding(vertices, capture.vertices, capture.triangles)
    points = tuple(cube.ordered_outer_ring(anchor) for anchor in anchors)
    guides = build_topology_guide_binding(vertices, faces, regions, indices, points)
    return skin, guides


def _result_warnings(capture, warnings, density, metrics, budgets, transitions=()):
    values = list(capture.warnings) + list(warnings) + list(density[3])
    values.extend(budget_warnings(budgets))
    values.extend(transition_warnings(transitions))
    if metrics["self_intersections"]:
        values.append(f"Detected {metrics['self_intersections']} local self-intersections.")
    return values


def transition_warnings(transitions):
    staged = [item for item in transitions if item.get("mode") == "STAGED"]
    warnings = [f"Topology guide '{item['guide_name']}' used staged transition: {item['fallback_reason']}." for item in staged]
    warnings.extend(f"LOOP annuli retained, but joining strips are missing; skin has open seams: {item['fallback_reason']}"
                    for item in transitions if item.get("mode") == "UNSTITCHED")
    return warnings


def _result_stats(capture, metrics, target, guide_map, warnings, budgets, refinement,
                  transitions=()):
    return dict(metrics, input_hash=capture.input_hash, internal_target=target,
                requested_quads=capture.settings.target_quad_count,
                guide_map=guide_map, warnings=warnings,
                adaptive_density=has_adaptive_density(capture),
                density_backend=_density_backend(capture), topology_budgets=budgets,
                owner_map={item.scp_index: item.scp_id for item in capture.density_rules},
                refinement_strategy=capture.settings.refinement_strategy,
                refinement_statistics=refinement,
                transition_statistics=list(transitions))


def _warm_statistics(capture, vertices, faces, guide_map):
    guides = _patch_guides(capture.guides, guide_map)
    layouts = [{"guide_index": item.guide_index, "fiber_id": item.fiber_id,
                "points": np.asarray(item.points).tolist()} for item in guides]
    return {"structural_signature": structural_signature(len(vertices), faces),
            "skin_structural_signature": structural_signature(len(capture.vertices), capture.triangles),
            "guide_layout_signature": guide_layout_signature(guides),
            "source_guide_layout_signature": guide_layout_signature(capture.guides),
            "guide_pairing_signature": guide_pairing_signature(capture.guides),
            "symmetry_settings_signature": _symmetry_signature(capture),
            "density_settings_signature": _density_signature(capture),
            "guide_layout": layouts}


def _symmetry_signature(capture):
    settings = capture.settings
    payload = (settings.symmetry_mode, settings.custom_origin, settings.custom_normal)
    return settings_signature(payload)


def _density_signature(capture):
    payload = {"target": capture.settings.target_quad_count,
               "refinement": capture.settings.refinement_strategy,
               "rules": [asdict(item) for item in capture.density_rules]}
    return settings_signature(payload)


def _patch_guides(guides, guide_map):
    by_name = {item.object_name: item for item in guides}
    values = []
    for index, mapping in enumerate(guide_map):
        candidates = [by_name[name] for name in mapping["sources"] if name in by_name]
        if candidates:
            source = max(candidates, key=lambda item: _loop_perimeter(item.points))
            values.append(TopologyGuide(index, source.fiber_id, source.object_name,
                                        source.mirror_role, source.points))
    return tuple(values)


def _loop_perimeter(points):
    values = np.asarray(points)
    return float(np.linalg.norm(np.roll(values, -1, axis=0) - values, axis=1).sum())


def _density_backend(capture):
    return "CONFORMING_QUAD_REFINEMENT" if has_adaptive_density(capture) else capture.settings.backend


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
            "self_intersections": None,
            "valence": instant.valence_metrics(len(vertices), counts)}


def _fidelity(vertices, capture):
    bvh = guides.surface_bvh(capture.vertices, capture.triangles)
    distances = [np.linalg.norm(np.asarray(guides._nearest(bvh, point)[0]) - point)
                 for point in vertices]
    return float(np.quantile(distances, 0.95))


def _safe_bindings(capture, vertices, faces, regions, indices, anchors, stats):
    try:
        return _result_bindings(capture, vertices, faces, regions, indices, anchors)
    except (ValueError, RuntimeError, MemoryError) as error:
        stats["warnings"].append(f"Persistent bindings unavailable: {error}")
        stats["binding_available"] = False
        return None, None
