"""Benchmark isolated Fiber V2.1 against V1 and Package 6.1."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot, clear_native_collision_world_cache,
    clear_structural_cache, clear_v21_route_cache, solve_package61, solve_v21)
from anthroforge.tools import fiber_v2_package5_benchmark as p5
from anthroforge.tools import fiber_v2_package6_benchmark as p6
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=5)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _once(call):
    started = perf_counter(); result = call()
    return 1000.0 * (perf_counter() - started), result


def _summary(values):
    ordered = sorted(values); index = min(len(ordered) - 1, int(np.ceil(.95 * len(ordered))) - 1)
    return {"median_ms": statistics.median(values), "p95_ms": ordered[index], "max_ms": max(values)}


def _measure(call, repeats):
    times, rows = [], []
    for _index in range(max(1, repeats)):
        elapsed, row = _once(call); times.append(elapsed); rows.append(row)
    return _summary(times), rows


def _clear_v2(clear_routes=False):
    clear_native_collision_world_cache(); clear_structural_cache()
    if clear_routes:
        clear_v21_route_cache()


def _variant(request, index):
    factor = 1.0 + 0.025 * (index + 1)
    settings = replace(request.settings, curvature_weight=request.settings.curvature_weight * factor)
    return replace(request, token=request.token + index + 1, settings=settings)


def _variant_measure(solver, request, snapshot, repeats):
    rows = [_variant(request, index) for index in range(max(1, repeats))]
    signatures = [_once(row.signature)[0] for row in rows]; times, results = [], []
    for row in rows:
        elapsed, result = _once(lambda row=row: solver(row, snapshot)); times.append(elapsed); results.append(result)
    return _summary(times), results, _summary(signatures)


def _handle_variant(request, index):
    anchors = list(request.anchors); target = 1 if len(anchors) > 2 else len(anchors) - 1
    neighbor = target + 1 if target + 1 < len(anchors) else target - 1
    direction = np.asarray(anchors[neighbor].point) - anchors[target].point
    direction /= max(float(np.linalg.norm(direction)), 1.0e-12)
    distance = 0.1 * (index + 1) * request.collision_policy.collision_radius
    anchors[target] = replace(anchors[target], point=tuple(np.asarray(anchors[target].point) + distance * direction))
    return replace(request, token=request.token + index + 100, anchors=tuple(anchors))


def _handle_measure(solver, request, snapshot, repeats):
    rows = [_handle_variant(request, index) for index in range(max(1, repeats))]
    signatures = [_once(row.signature)[0] for row in rows]; times, results = [], []
    for row in rows:
        elapsed, result = _once(lambda row=row: solver(row, snapshot)); times.append(elapsed); results.append(result)
    return _summary(times), results, _summary(signatures)


def _solver_payload(timing, rows, request, snapshot):
    payload = p6._solver_payload([timing["median_ms"]], rows[-1:], request, snapshot)
    payload["timing"] = timing; return payload


def _edit_payload(measured, request, snapshot):
    payload = _solver_payload(measured[0], measured[1], request, snapshot)
    payload["request_signature_timing"] = measured[2]; return payload


def _v1_payload(timing, points, request, snapshot):
    payload = p5._v1_payload([timing["median_ms"]], points, request, snapshot)
    payload["timing"] = timing; return payload


def _measure_solvers(root, fiber, depsgraph, request, snapshot, repeats):
    v1 = _measure(lambda: p5._v1_solve(root, fiber, depsgraph), repeats)
    _clear_v2(); p61 = _measure(lambda: solve_package61(request, snapshot), repeats)
    _clear_v2(True); cold = _once(lambda: solve_v21(request, snapshot))
    exact = _measure(lambda: solve_v21(request, snapshot), repeats)
    p61_edit = _variant_measure(solve_package61, request, snapshot, repeats)
    solve_v21(request, snapshot); v21_edit = _variant_measure(solve_v21, request, snapshot, repeats)
    p61_handle = _handle_measure(solve_package61, request, snapshot, repeats)
    clear_v21_route_cache(); solve_v21(request, snapshot)
    v21_handle = _handle_measure(solve_v21, request, snapshot, repeats)
    return v1, p61, cold, exact, p61_edit, v21_edit, p61_handle, v21_handle


def _delta(first, second):
    a, b = np.asarray(first.result.points), np.asarray(second.result.points)
    return float(np.max(np.linalg.norm(a - b, axis=1))) if a.shape == b.shape else None


def _visual(request, v1, p61, v21, snapshot):
    routes = (np.asarray(v1), np.asarray(p61.result.points), np.asarray(v21.result.points))
    payload = {key: route.tolist() for key, route in zip(("v1", "package61", "v21"), routes)}
    payload["anchors"] = [list(anchor.point) for anchor in request.anchors]
    payload["nearby_triangles"] = p41._nearby_faces(snapshot, routes).tolist(); return payload


def _handle_visual(p61, v21, snapshot):
    routes = (np.asarray(p61.result.points), np.asarray(v21.result.points))
    return {"package61": routes[0].tolist(), "v21": routes[1].tolist(),
            "nearby_triangles": p41._nearby_faces(snapshot, routes).tolist()}


def _payload(root, fiber, request, snapshot, capture, rows):
    v1, p61, cold, exact, p61_edit, v21_edit, p61_handle, v21_handle = rows
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "fiber_id": fiber.id, "fiber_name": fiber.name, "root": root.name,
            "triangles": len(snapshot.triangles), "colliders": snapshot.source_count, "capture_ms": capture,
            "v1": _v1_payload(v1[0], v1[1][-1], request, snapshot),
            "package61": _solver_payload(p61[0], p61[1], request, snapshot),
            "v21_cold_ms": cold[0], "v21": _solver_payload(exact[0], exact[1], request, snapshot),
            "package61_edit": _edit_payload(p61_edit, request, snapshot),
            "v21_edit": _edit_payload(v21_edit, request, snapshot),
            "package61_handle": _edit_payload(p61_handle, request, snapshot),
            "v21_handle": _edit_payload(v21_handle, request, snapshot),
            "handle_delta": _delta(p61_handle[1][-1], v21_handle[1][-1]),
            "p61_v21_delta": _delta(p61[1][-1], exact[1][-1]),
            "visual": _visual(request, v1[1][-1], p61[1][-1], exact[1][-1], snapshot),
            "visual_handle": _handle_visual(p61_handle[1][-1], v21_handle[1][-1], snapshot)}


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    started = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
    request = bench._request(root, fiber, anchors, colliders); capture = 1000.0 * (perf_counter() - started)
    rows = _measure_solvers(root, fiber, depsgraph, request, snapshot, args.repeats)
    return _payload(root, fiber, request, snapshot, capture, rows)


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    keys = ("v1", "package61", "v21", "package61_edit", "v21_edit",
            "package61_handle", "v21_handle")
    print("AF_V21", json.dumps({key: record[key]["timing"] for key in keys}), flush=True)


if __name__ == "__main__":
    main()
