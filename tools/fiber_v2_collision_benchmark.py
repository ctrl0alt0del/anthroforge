"""Read-only real-file benchmark for Fiber V2 Package 3 collision."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import sys
import time

import bpy
from mathutils import Vector
import numpy as np

from anthroforge.core.vcp.v2 import (
    V2ColliderSnapshot, V2OwnerContact, build_triangle_snapshot,
    collision_backend_status, collision_free_step, validate_static_clearance,
)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--counts", default="64,256,512")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--motion", type=float, default=0.002)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _root():
    roots = [obj for obj in bpy.context.scene.objects if obj.get("anthroforge_root")]
    return next((obj for obj in roots if len(obj.af_vcp_system.fibers)), None)


def _fiber(root, identifier):
    return next((item for item in root.af_vcp_system.fibers
                 if item.id == identifier or item.name == identifier), None)


def _proxy(root, identifier):
    return next((obj for obj in bpy.context.scene.objects if obj.get("af_fiber_proxy")
                 and not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name
                 and str(obj.get("af_fiber_id")) == str(identifier)), None)


def _curve_points(proxy):
    values = []
    for spline in proxy.data.splines:
        source = spline.bezier_points if spline.type == "BEZIER" else spline.points
        values.extend(proxy.matrix_world @ (point.co if spline.type == "BEZIER" else point.co.xyz)
                      for point in source)
    return np.asarray([tuple(value) for value in values], dtype=np.float64)


def _surface(obj, depsgraph):
    from anthroforge.core.scp_runtime.surface import build_mesh_surface_data
    data = build_mesh_surface_data(obj, depsgraph, cache={})
    vertices = np.asarray([tuple(value) for value in data.get("verts_world", ())])
    return vertices, np.asarray(data.get("triangles", ()), dtype=np.int64)


def _colliders(scene, root, depsgraph):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    records = []
    for index, obj in enumerate(iter_geometry_mesh_scp_objects(scene, root.name)):
        vertices, triangles = _surface(obj, depsgraph)
        if len(vertices) and len(triangles):
            owner = str(obj.get("af_scp_id", "") or "")
            records.append(V2ColliderSnapshot(f"{owner}:{index}", owner, tuple(map(tuple, vertices)),
                                               tuple(map(tuple, triangles))))
    return tuple(records)


def _resample(points, count):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    distances = np.concatenate(([0.0], np.cumsum(lengths)))
    targets = np.linspace(0.0, distances[-1], count)
    indices = np.clip(np.searchsorted(distances, targets, side="right") - 1, 0, len(points) - 2)
    spans = distances[indices + 1] - distances[indices]
    fractions = np.divide(targets - distances[indices], spans, out=np.zeros(count), where=spans > 0)
    return points[indices] + fractions[:, None] * (points[indices + 1] - points[indices])


def _pin_owners(root, scene, depsgraph, fiber, points):
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    solver = FiberSolver(); _runtime, anchors, issue = solver._open_anchors(root, scene, depsgraph, fiber)
    if issue:
        return {}
    route = [Vector(value) for value in points]
    targets = solver._anchor_pin_targets(route, anchors, len(points))
    return solver._pin_owners(anchors, targets)


def _contact_edges(points, index, radius):
    rows = []
    if index > 0:
        fraction = _contact_fraction(points[index - 1], points[index], radius)
        rows.append((index - 1, 1.0 - fraction, 1.0))
    if index + 1 < len(points):
        fraction = _contact_fraction(points[index], points[index + 1], radius)
        rows.append((index, 0.0, fraction))
    return tuple(rows)


def _contact_fraction(start, end, radius):
    length = float(np.linalg.norm(end - start))
    return min(0.25, max(0.001, 2.0 * radius / max(length, 1.0e-12)))


def _contacts(root, scene, depsgraph, fiber, points, radius):
    owners = _pin_owners(root, scene, depsgraph, fiber, points)
    return tuple(V2OwnerContact(owner, (index,), _contact_edges(points, index, radius))
                 for index, owner in sorted(owners.items()) if owner)


def _motion(points, amplitude):
    parameter = np.linspace(0.0, np.pi, len(points))
    moved = points.copy(); moved[:, 2] += amplitude * np.sin(parameter)
    return moved


def _timed(call, repeats):
    values, result = [], None
    for _index in range(max(1, repeats)):
        started = time.perf_counter(); result = call()
        values.append(1000.0 * (time.perf_counter() - started))
    return values, result


def _summary(values):
    ordered = sorted(values); p95 = ordered[min(len(ordered) - 1, int(np.ceil(.95 * len(ordered))) - 1)]
    return {"median_ms": statistics.median(values), "p95_ms": p95, "max_ms": max(values)}


def _finite(value):
    return float(value) if np.isfinite(value) else None


def _static_payload(result, timings):
    return {"timing": _summary(timings), "valid": result.valid, "reason": result.reason.value,
            "node_minimum": _finite(result.node_minimum), "edge_minimum": _finite(result.edge_minimum),
            "node_residual": result.node_residual, "edge_residual": result.edge_residual,
            "candidate_pairs": result.candidate_pairs, "tested_pairs": result.tested_pairs,
            "violating_nodes": list(result.violating_nodes), "violating_edges": list(result.violating_edges),
            "contained_nodes": list(result.contained_nodes)}


def _sweep_payload(result, timings):
    return {"timing": _summary(timings), "valid": result.valid,
            "initially_valid": result.initially_valid, "reason": result.reason.value,
            "safe_step": result.safe_step, "candidate_pairs": result.candidate_pairs,
            "tested_pairs": result.tested_pairs, "intervals": result.intervals,
            "max_edge_batch": result.max_edge_batch, "max_pair_batch": result.max_pair_batch}


def _benchmark_count(root, fiber, points, snapshot, radius, motion, repeats, depsgraph, probe):
    contacts = _contacts(root, bpy.context.scene, depsgraph, fiber, points, radius)
    static_times, static = _timed(lambda: validate_static_clearance(
        points, snapshot, radius, contacts), repeats)
    target = _motion(points, motion)
    sweep_times, sweep = _timed(lambda: collision_free_step(
        points, target, snapshot, radius, contacts), repeats)
    probe_points, probe_target = _probe_curve(probe, len(points), radius)
    probe_times, probe_result = _timed(lambda: collision_free_step(
        probe_points, probe_target, snapshot, radius), repeats)
    reference_times, reference = _timed(lambda: _reference_probe(
        probe_points, probe_target, snapshot, radius), 1)
    return {"contacts": len(contacts), "static": _static_payload(static, static_times),
            "sweep": _sweep_payload(sweep, sweep_times),
            "ccd_probe": _sweep_payload(probe_result, probe_times),
            "reference_ccd_probe": _reference_payload(reference, reference_times)}


def _reference_probe(start, end, snapshot, radius):
    from anthroforge.core.vcp.fiber_ccd_reference import mesh_collision_free_step_reference
    edges = np.column_stack((np.arange(len(start) - 1), np.arange(1, len(start))))
    return mesh_collision_free_step_reference(start, end, edges, snapshot.vertices,
                                              snapshot.triangles, radius)


def _reference_payload(result, timings):
    return {"timing": _summary(timings), "safe_step": result.safe_step,
            "initially_valid": result.initially_valid, "reason": result.reason,
            "candidate_pairs": result.candidate_pairs, "tested_pairs": result.tested_pairs,
            "intervals": result.intervals}


def _probe_curve(probe, count, radius):
    face, normal = probe; center = face.mean(axis=0); direction = 0.15 * (face[1] - face[0])
    line = np.linspace(center - direction, center + direction, count)
    offset = normal * max(4.0 * radius, 1.0e-5)
    return line + offset, line - offset


def _find_probe(snapshot, radius):
    faces = snapshot.vertices[snapshot.triangles]
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    lengths = np.linalg.norm(normals, axis=1); order = np.argsort(lengths)[::-1]
    for index in order[:min(300, len(order))]:
        if lengths[index] <= 1.0e-12:
            continue
        normal = normals[index] / lengths[index]
        for sign in (1.0, -1.0):
            start, end = _probe_curve((faces[index], sign * normal), 8, radius)
            result = collision_free_step(start, end, snapshot, radius)
            if result.initially_valid and result.safe_step < 1.0:
                return faces[index], sign * normal
    raise RuntimeError("No valid real-mesh CCD probe could be constructed")


def _visual(snapshot, points, static):
    span = np.ptp(points, axis=0); padding = max(float(np.linalg.norm(span)) * 0.2, 0.05)
    low, high = points.min(axis=0) - padding, points.max(axis=0) + padding
    faces = snapshot.vertices[snapshot.triangles]
    selected = np.flatnonzero(np.all(faces.max(axis=1) >= low, axis=1) & np.all(faces.min(axis=1) <= high, axis=1))
    if len(selected) > 4000:
        selected = selected[np.linspace(0, len(selected) - 1, 4000).astype(int)]
    return {"points": points.tolist(), "violating_edges": list(static.violating_edges),
            "nearby_triangles": faces[selected].tolist(), "nearby_face_count": len(selected)}


def _file_hash(path):
    digest = sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _record(args, root, fiber, source, colliders, snapshot, depsgraph, capture_ms):
    radius = float(getattr(fiber, "collision_radius", 0.002)); rows, visual = {}, None
    probe = _find_probe(snapshot, radius)
    for count in [int(value) for value in args.counts.split(",") if value.strip()]:
        points = _resample(source, count)
        rows[str(count)] = _benchmark_count(root, fiber, points, snapshot, radius,
                                             args.motion, args.repeats, depsgraph, probe)
        if count == int(fiber.node_count):
            contacts = _contacts(root, bpy.context.scene, depsgraph, fiber, points, radius)
            static = validate_static_clearance(points, snapshot, radius, contacts)
            visual = _visual(snapshot, points, static)
    return _record_payload(args, root, fiber, colliders, snapshot, rows, visual, capture_ms, radius)


def _record_payload(args, root, fiber, colliders, snapshot, rows, visual, capture_ms, radius):
    path = str(bpy.data.filepath); status = collision_backend_status()
    return {"file": path, "file_sha256": _file_hash(path), "root": root.name,
            "fiber_id": fiber.id, "fiber_name": fiber.name, "stored_count": int(fiber.node_count),
            "collision_radius": radius, "backend": status.version, "backend_available": status.available,
            "colliders": len(colliders), "vertices": len(snapshot.vertices), "triangles": len(snapshot.triangles),
            "snapshot_capture_ms": capture_ms, "motion": args.motion, "repeats": args.repeats,
            "blender": bpy.app.version_string, "python": platform.python_version(),
            "processor": platform.processor(), "counts": rows, "visual": visual}


def main():
    args = _arguments(); root = _root()
    if root is None:
        raise RuntimeError("No AnthroForge root with Fibers was found")
    fiber = _fiber(root, args.fiber_id); proxy = _proxy(root, fiber.id if fiber else "")
    if fiber is None or proxy is None:
        raise RuntimeError(f"Fiber {args.fiber_id} was not found")
    depsgraph = bpy.context.evaluated_depsgraph_get(); started = time.perf_counter()
    colliders = _colliders(bpy.context.scene, root, depsgraph); snapshot = build_triangle_snapshot(colliders)
    capture_ms = 1000.0 * (time.perf_counter() - started)
    record = _record(args, root, fiber, _curve_points(proxy), colliders, snapshot, depsgraph, capture_ms)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_COLLISION", json.dumps(record["counts"]), flush=True)


main()
