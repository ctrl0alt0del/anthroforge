"""Read-only Package 4 planner benchmark on a loaded Blender production file."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import sys
import time

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (
    V2Anchor, V2AnchorRole, V2ColliderSnapshot, V2CollisionPolicy, V2Quality,
    V2Request, V2ResolvedTolerances, V2Settings, V2Topology,
    build_triangle_snapshot, collision_backend_status, plan_reference,
    validate_static_clearance,
)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=5)
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
    rows = []
    for index, obj in enumerate(iter_geometry_mesh_scp_objects(scene, root.name)):
        vertices, triangles = _surface(obj, depsgraph)
        if len(vertices) and len(triangles):
            owner = str(obj.get("af_scp_id", "") or "")
            rows.append(V2ColliderSnapshot(f"{owner}:{index}", owner, tuple(map(tuple, vertices)),
                                           tuple(map(tuple, triangles))))
    return tuple(rows)


def _open_anchors(root, fiber, depsgraph):
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    _runtime, anchors, issue = FiberSolver()._open_anchors(root, bpy.context.scene, depsgraph, fiber)
    if issue or anchors is None:
        raise RuntimeError(issue or "invalid Fiber anchors")
    roles = [V2AnchorRole.TOUCH] * len(anchors)
    roles[0], roles[-1] = V2AnchorRole.ENDPOINT_A, V2AnchorRole.ENDPOINT_B
    return tuple(V2Anchor(tuple(anchor.point), anchor.owner_id, roles[index], index)
                 for index, anchor in enumerate(anchors)), anchors


def _tolerances(colliders, radius, quality):
    points = np.asarray([point for collider in colliders for point in collider.vertices])
    diagonal = float(np.linalg.norm(np.ptp(points, axis=0))) if len(points) else radius
    length_scale = max(diagonal, radius, 1.0e-6)
    coordinate = max(1.0, float(np.max(np.abs(points))) if len(points) else 1.0, length_scale)
    floor = max(1.0e-9 * length_scale, 8.0 * np.finfo(np.float32).eps * coordinate)
    slack = max(floor, 0.01 * radius) if radius > 0.0 else floor
    fixed = 1.0e-6 if quality is V2Quality.FINAL else 1.0e-4
    return V2ResolvedTolerances(length_scale, coordinate, floor, slack,
                                max(1.0e-7, 1.0e-6 * length_scale), fixed, fixed,
                                1.0e-7 if quality is V2Quality.FINAL else 1.0e-5)


def _request(root, fiber, anchors, colliders):
    quality = V2Quality.INTERACTIVE; radius = float(fiber.collision_radius)
    settings = V2Settings(V2Topology.OPEN, quality, int(fiber.node_count),
                          int(fiber.iterations_interactive), float(fiber.stretch_stiffness),
                          float(fiber.bend_stiffness), 1.0)
    status = collision_backend_status()
    policy = V2CollisionPolicy(radius, backend_version=status.version)
    revision = f"{fiber.id}:{fiber.name}:{fiber.node_count}"
    return V2Request(1, str(bpy.context.scene.as_pointer()), str(root.as_pointer()), revision,
                     settings, _tolerances(colliders, radius, quality), policy, anchors, colliders)


def _v1_plan(root, fiber, anchors, depsgraph):
    from anthroforge.core.vcp.fiber_collision import CollisionOracle
    from anthroforge.core.vcp.fiber_planner import plan_route
    oracle = CollisionOracle(root, bpy.context.scene, depsgraph,
                             margin=float(fiber.collision_radius))
    return plan_route(oracle, anchors, allow_dense=False)


def _timed(call, repeats):
    times, values = [], []
    for _index in range(max(1, repeats)):
        started = time.perf_counter(); values.append(call())
        times.append(1000.0 * (time.perf_counter() - started))
    return times, values


def _summary(values):
    ordered = sorted(values); index = min(len(ordered) - 1, int(np.ceil(.95 * len(ordered))) - 1)
    return {"median_ms": statistics.median(values), "p95_ms": ordered[index], "max_ms": max(values)}


def _strict_validation(points, anchors, snapshot, radius, slack):
    from anthroforge.core.vcp.v2.planner import _anchor_contact
    indices = [int(np.argmin(np.linalg.norm(points - np.asarray(anchor.point), axis=1)))
               for anchor in anchors]
    contacts = tuple(_anchor_contact(points, index, anchor.owner_id, max(2.5 * radius, 1e-7), False)
                     for anchor, index in zip(anchors, indices) if anchor.owner_id)
    return validate_static_clearance(points, snapshot, radius, contacts, slack=slack)


def _validation_payload(result):
    if result is None:
        return {"valid": False, "unavailable": True}
    return {"valid": result.valid, "node_residual": result.node_residual,
            "edge_residual": result.edge_residual, "violating_nodes": list(result.violating_nodes),
            "violating_edges": list(result.violating_edges), "contained_nodes": list(result.contained_nodes),
            "candidate_pairs": result.candidate_pairs, "tested_pairs": result.tested_pairs}


def _route_payload(points):
    values = np.asarray(points, dtype=np.float64)
    return {"points": values.tolist(), "count": len(values), "length": _length(values)}


def _length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()) if len(points) > 1 else 0.0


def _v1_payload(times, result, validation):
    return {"timing": _summary(times), "mode": result.mode,
            "active_ids": list(result.active_ids), "route": _route_payload(result.points),
            "validation": _validation_payload(validation)}


def _v2_payload(times, result, validation, deterministic):
    return {"timing": _summary(times), "termination": result.termination.value,
            "mode": result.mode.value, "message": result.message,
            "route": _route_payload(result.corridor), "reference": _route_payload(result.reference),
            "pin_indices": list(result.pin_indices), "diagnostics": vars(result.diagnostics),
            "validation": _validation_payload(validation), "deterministic": deterministic}


def _deterministic(results):
    first = results[0]
    return all(item.reference == first.reference and item.corridor == first.corridor
               and item.pin_indices == first.pin_indices for item in results[1:])


def _visual(snapshot, source, v1, v2):
    routes = [source, np.asarray(v1.points), np.asarray(v2.reference)]
    points = np.vstack([row for row in routes if len(row)])
    padding = max(float(np.linalg.norm(np.ptp(points, axis=0))) * 0.15, 0.05)
    low, high = points.min(axis=0) - padding, points.max(axis=0) + padding
    faces = snapshot.vertices[snapshot.triangles]
    selected = np.flatnonzero(np.all(faces.max(axis=1) >= low, axis=1) & np.all(faces.min(axis=1) <= high, axis=1))
    selected = selected if len(selected) <= 5000 else selected[np.linspace(0, len(selected) - 1, 5000).astype(int)]
    return {"source": source.tolist(), "v1": np.asarray(v1.points).tolist(),
            "v2_corridor": list(v2.corridor), "v2_reference": list(v2.reference),
            "anchors": [list(point) for point in source[[0, -1]]],
            "nearby_triangles": faces[selected].tolist()}


def _file_hash(path):
    digest = sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _record(args, root, fiber, proxy, depsgraph):
    capture = time.perf_counter(); colliders = _colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); capture_ms = 1000.0 * (time.perf_counter() - capture)
    anchors, legacy = _open_anchors(root, fiber, depsgraph); request = _request(root, fiber, anchors, colliders)
    v1_times, v1_rows = _timed(lambda: _v1_plan(root, fiber, legacy, depsgraph), args.repeats)
    v2_times, v2_rows = _timed(lambda: plan_reference(request, snapshot), args.repeats)
    return _record_payload(args, root, fiber, proxy, request, snapshot, capture_ms,
                           v1_times, v1_rows, v2_times, v2_rows)


def _record_payload(args, root, fiber, proxy, request, snapshot, capture_ms, v1_times, v1_rows, v2_times, v2_rows):
    source = _curve_points(proxy); v1, v2 = v1_rows[-1], v2_rows[-1]
    radius, slack = request.collision_policy.collision_radius, request.tolerances.clearance_slack
    v1_validation = _strict_validation(np.asarray(v1.points), request.anchors, snapshot, radius, slack)
    v2_validation = _v2_validation(v2, snapshot, radius, slack)
    path = str(bpy.data.filepath)
    return {"file": path, "file_sha256": _file_hash(path), "root": root.name,
            "fiber_id": fiber.id, "fiber_name": fiber.name, "node_count": int(fiber.node_count),
            "collision_radius": radius, "colliders": snapshot.source_count,
            "triangles": len(snapshot.triangles), "snapshot_capture_ms": capture_ms,
            "blender": bpy.app.version_string, "python": platform.python_version(),
            "processor": platform.processor(), "repeats": args.repeats,
            "v1": _v1_payload(v1_times, v1, v1_validation),
            "v2": _v2_payload(v2_times, v2, v2_validation, _deterministic(v2_rows)),
            "visual": _visual(snapshot, source, v1, v2)}


def _v2_validation(result, snapshot, radius, slack):
    if len(result.reference) < 2:
        return None
    return validate_static_clearance(result.reference, snapshot, radius,
                                     result.contacts, slack=slack)


def main():
    args = _arguments(); root = _root()
    if root is None:
        raise RuntimeError("No AnthroForge root with Fibers was found")
    fiber = _fiber(root, args.fiber_id); proxy = _proxy(root, fiber.id if fiber else "")
    if fiber is None or proxy is None:
        raise RuntimeError(f"Fiber {args.fiber_id} was not found")
    record = _record(args, root, fiber, proxy, bpy.context.evaluated_depsgraph_get())
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PLANNER", json.dumps({"v1": record["v1"], "v2": record["v2"]}), flush=True)


if __name__ == "__main__":
    main()
