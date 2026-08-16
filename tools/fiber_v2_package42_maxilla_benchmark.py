"""Read-only Package 4/4.1/4.2 benchmark for Maxilla Top Radius and FIBER_21."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_planner_benchmark as bench

from anthroforge.core.vcp.v2 import (cached_triangle_snapshot, clear_triangle_snapshot_cache,
                                     plan_reference,
                                     plan_reference_v41, plan_reference_v42, plan_reference_v43,
                                     triangle_snapshot_cache_stats, validate_static_clearance)
from anthroforge.core.vcp.v2.collision import _inside_memberships
from anthroforge.core.vcp.v2 import collision as collision_impl
from anthroforge.core.vcp.v2 import planner as planner_impl
from anthroforge.core.visualization import sync_runner
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--value", type=float, default=.2); parser.add_argument("--repeats", type=int, default=3)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _shortcut(root):
    return next(row for row in root.af_shortcut_system.shortcuts if row.name == "Maxilla Top Radius")


def _force_ready():
    for item in sync_runner._PENDING:
        item.due_at = 0.0


def _flush_runtime(limit=32):
    passes = 0
    while (sync_runner._PENDING or sync_runner._TAIL_PENDING) and passes < limit:
        _force_ready(); sync_runner._flush_pending(); passes += 1
    return passes


def _settle():
    passes = 0
    for _index in range(6):
        bpy.context.view_layer.update(); passes += _flush_runtime()
        drain_fiber_refinements(); passes += _flush_runtime()
    return passes


def _curve(root, fiber):
    proxy = bench._proxy(root, fiber.id)
    return bench._curve_points(proxy).tolist()


def _hash(path):
    digest = sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _timed(call, repeats):
    values, times = [], []
    for _index in range(max(1, repeats)):
        started = time.perf_counter(); values.append(call())
        times.append(1000.0 * (time.perf_counter() - started))
    return values, times


def _summary(times):
    return {"median_ms": statistics.median(times), "min_ms": min(times), "max_ms": max(times)}


def _validation(result, request, snapshot):
    if len(result.reference) < 2:
        return {"valid": False, "unavailable": True}
    checked = validate_static_clearance(result.reference, snapshot,
                                        request.collision_policy.collision_radius,
                                        result.contacts, slack=request.tolerances.clearance_slack)
    return {"valid": checked.valid, "node_residual": checked.node_residual,
            "edge_residual": checked.edge_residual, "violating_edges": list(checked.violating_edges)}


def _planner_row(call, repeats, request, snapshot):
    results, times = _timed(call, repeats); result = results[-1]
    return {"timing": _summary(times), "termination": result.termination.value,
            "mode": result.mode.value, "message": result.message,
            "corridor": [list(point) for point in result.corridor],
            "reference": [list(point) for point in result.reference],
            "pins": list(result.pin_indices), "diagnostics": vars(result.diagnostics),
            "validation": _validation(result, request, snapshot)}


def _live_validation(points, request, snapshot):
    checked = bench._strict_validation(np.asarray(points), request.anchors, snapshot,
                                       request.collision_policy.collision_radius,
                                       request.tolerances.clearance_slack)
    return {"valid": checked.valid, "node_residual": checked.node_residual,
            "edge_residual": checked.edge_residual, "violating_edges": list(checked.violating_edges),
            "contained_nodes": list(checked.contained_nodes)}


def _nearby(snapshot, routes):
    cloud = np.vstack([np.asarray(route) for route in routes if len(route)])
    pad = max(float(np.linalg.norm(np.ptp(cloud, axis=0))) * .15, .05)
    low, high = cloud.min(0) - pad, cloud.max(0) + pad; faces = snapshot.vertices[snapshot.triangles]
    chosen = np.flatnonzero(np.all(faces.max(1) >= low, 1) & np.all(faces.min(1) <= high, 1))
    chosen = chosen if len(chosen) <= 6000 else chosen[np.linspace(0, len(chosen)-1, 6000).astype(int)]
    return faces[chosen].tolist()


def _planner_rows(request, snapshot, repeats):
    calls = (("package4", lambda: plan_reference(request, snapshot)),
             ("package41", lambda: plan_reference_v41(request, snapshot)),
             ("package42", lambda: plan_reference_v42(request, snapshot)),
             ("package43", lambda: plan_reference_v43(request, snapshot)))
    return {name: _planner_row(call, repeats, request, snapshot) for name, call in calls}


def _anchor_memberships(request, snapshot):
    points = np.asarray([anchor.point for anchor in request.anchors])
    rows = _inside_memberships(points, snapshot, None)
    return [{"owner": anchor.owner_id, "inside": sorted(rows.get(index, ())) }
            for index, anchor in enumerate(request.anchors)]


def _surface_variant_rows(request, snapshot, collider, factor, sign):
    points = np.asarray(collider.vertices); faces = np.asarray(collider.triangles)
    normals = planner_impl._vertex_normals(points, faces); graph = planner_impl._mesh_graph(points, faces)
    distance = request.collision_policy.collision_radius * factor * sign
    offset = points + normals * distance
    anchors = request.anchors[2:6]; lifts = planner_impl._surface_anchor_lifts(points, normals, anchors, distance)
    state = planner_impl._PlannerState(request, snapshot, {}, {})
    routes = [planner_impl._surface_graph_pair(state, offset, graph, a, b, lifts[i:i + 2])
              for i, (a, b) in enumerate(zip(anchors[:-1], anchors[1:]))]
    return {"factor": factor, "sign": sign, "success": [route is not None for route in routes]}


def _surface_probe(request, snapshot):
    colliders = [item for item in request.colliders if item.owner_id == "SCP_10"]
    rows = []
    for collider in colliders:
        rows.extend(_surface_variant_rows(request, snapshot, collider, factor, sign)
                    for factor in planner_impl._SURFACE_FACTORS for sign in (1.0, -1.0))
    return rows


def _direct_blockers(request, snapshot):
    rows, threshold = [], request.collision_policy.collision_radius - request.tolerances.clearance_slack
    for index, (start, end) in enumerate(zip(request.anchors[:-1], request.anchors[1:])):
        points = np.asarray((start.point, end.point)); edges = np.asarray(((0, 1),), dtype=np.int64)
        pairs = collision_impl._candidate_pairs(points, points, edges, snapshot, threshold, None)
        segments, faces, _keys = collision_impl._segment_batch_rows(
            points, edges, snapshot, ((start.owner_id, end.owner_id),), 2.5 * request.collision_policy.collision_radius, pairs)
        distances = collision_impl._batch_face_distances(segments, faces, snapshot, None)
        blocked = sorted({snapshot.face_colliders[int(face)] for face, distance in zip(faces, distances)
                          if distance < threshold})
        rows.append({"pair": index, "owners": [start.owner_id, end.owner_id], "blockers": blocked})
    return rows


def _anchor_clearance(request, snapshot):
    points = np.asarray([anchor.point for anchor in request.anchors]); radius = request.collision_policy.collision_radius
    contacts = tuple(collision_impl.V2OwnerContact(anchor.owner_id, (index,), ())
                     for index, anchor in enumerate(request.anchors))
    distances, keys, _count, _inside = collision_impl._node_rows(
        points, snapshot, contacts, radius - request.tolerances.clearance_slack, None)
    rows = []
    for index in range(len(points)):
        blocked = sorted({snapshot.face_colliders[face] for distance, (node, face) in zip(distances, keys)
                          if node == index and distance < radius - request.tolerances.clearance_slack})
        rows.append(blocked)
    return rows


def _snapshot_probe(colliders, value):
    clear_triangle_snapshot_cache()
    key = ("maxilla", round(value, 12), tuple((row.collider_id, len(row.triangles)) for row in colliders))
    started = time.perf_counter(); snapshot = cached_triangle_snapshot(colliders, key)
    cold = 1000.0 * (time.perf_counter() - started); warm = []
    for _index in range(5):
        started = time.perf_counter(); cached_triangle_snapshot(colliders, key)
        warm.append(1000.0 * (time.perf_counter() - started))
    return snapshot, {"cold_ms": cold, "warm_ms": _summary(warm), "cache": triangle_snapshot_cache_stats()}


def _capture(args, root, fiber):
    before = _curve(root, fiber); started = time.perf_counter(); _shortcut(root).proxy_float = args.value
    passes = _settle(); update_ms = 1000.0 * (time.perf_counter() - started); after = _curve(root, fiber)
    depsgraph = bpy.context.evaluated_depsgraph_get(); started = time.perf_counter()
    colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot, cache = _snapshot_probe(colliders, args.value)
    capture_ms = 1000.0 * (time.perf_counter() - started)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
    return before, after, passes, update_ms, colliders, snapshot, bench._request(root, fiber, anchors, colliders), capture_ms, cache


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, "FIBER_21"); source_hash = _hash(bpy.data.filepath)
    before, after, passes, update_ms, colliders, snapshot, request, capture_ms, cache = _capture(args, root, fiber)
    planners = _planner_rows(request, snapshot, args.repeats)
    routes = [before, after, [anchor.point for anchor in request.anchors]]
    routes.extend(row["reference"] or row["corridor"] for row in planners.values())
    fixed = {"file": bpy.data.filepath, "source_sha256": source_hash, "fiber": fiber.id,
             "shortcut_value": float(_shortcut(root).proxy_float), "v1_update_ms": update_ms,
             "settle_passes": passes, "v1_before": before, "v1_after": after,
             "v1_rolled_back": before == after, "triangles": len(snapshot.triangles),
             "snapshot_capture_ms": capture_ms, "persistent_snapshot": cache}
    details = _record_details(request, snapshot, planners, routes, colliders, after)
    return fixed | details


def _record_details(request, snapshot, planners, routes, colliders, after):
    return {"v1_validation": _live_validation(after, request, snapshot),
            "anchors": [list(anchor.point) for anchor in request.anchors], "planners": planners,
            "anchor_memberships": _anchor_memberships(request, snapshot),
            "anchor_clearance_blockers": _anchor_clearance(request, snapshot),
            "direct_blockers": _direct_blockers(request, snapshot), "surface_probe": _surface_probe(request, snapshot),
            "nearby_triangles": _nearby(snapshot, routes), "collider_count": len(colliders)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: row["timing"] | {"termination": row["termination"]}
               for name, row in record["planners"].items()}
    print("AF_PACKAGE42_MAXILLA", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
