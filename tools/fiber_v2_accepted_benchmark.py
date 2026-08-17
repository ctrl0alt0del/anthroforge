"""Read-only full-cycle comparison of the accepted Fiber V2 components."""

import argparse
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (clear_native_collision_world_cache,
    clear_structural_cache, plan_reference_v41, plan_reference_v43,
    solve_package51, solve_package61, build_triangle_snapshot)
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


def _clear_v2():
    clear_native_collision_world_cache(); clear_structural_cache()


def _measure(call, repeats, clear=None):
    if clear:
        clear()
    cold_ms, cold = _once(call); warm_rows, warm_ms = [], []
    for _index in range(max(1, repeats)):
        elapsed, row = _once(call); warm_ms.append(elapsed); warm_rows.append(row)
    return {"cold_ms": cold_ms, "warm": _summary(warm_ms)}, cold, warm_rows


def _planner_payload(timing, result, request, snapshot):
    points = np.asarray(result.reference); checked = p5._validation(points, snapshot, request, result.contacts)
    return {"timing": timing, "termination": result.termination.value, "mode": result.mode.value,
            "route": p5._metrics(points), "validation": p5._validation_payload(checked),
            "diagnostics": vars(result.diagnostics), "message": result.message}


def _solver_payload(timing, rows, request, snapshot):
    payload = p6._solver_payload([timing["warm"]["median_ms"]], rows[-1:], request, snapshot)
    payload["timing"] = timing; return payload


def _v1_payload(timing, points, request, snapshot):
    payload = p5._v1_payload([timing["warm"]["median_ms"]], points, request, snapshot)
    payload["timing"] = timing; return payload


def _calls(root, fiber, depsgraph, request, snapshot):
    return {"v1": lambda: p5._v1_solve(root, fiber, depsgraph),
            "package41": lambda: plan_reference_v41(request, snapshot),
            "package43": lambda: plan_reference_v43(request, snapshot),
            "package51": lambda: solve_package51(request, snapshot),
            "package61": lambda: solve_package61(request, snapshot)}


def _measure_all(calls, repeats):
    _prime(calls); rows = {}; rows["v1"] = _measure(calls["v1"], repeats)
    for key in ("package41", "package43", "package51", "package61"):
        rows[key] = _measure(calls[key], repeats, _clear_v2)
    return rows


def _prime(calls):
    for call in calls.values():
        call()
    _clear_v2()


def _route_delta(first, second):
    a, b = np.asarray(first.reference), np.asarray(second.reference)
    return float(np.max(np.linalg.norm(a - b, axis=1))) if a.shape == b.shape else None


def _visual(request, rows, snapshot):
    routes = (np.asarray(rows["v1"][1]), np.asarray(rows["package43"][2][-1].reference),
              np.asarray(rows["package51"][2][-1].result.points), np.asarray(rows["package61"][2][-1].result.points))
    nearby = p41._nearby_faces(snapshot, routes); keys = ("v1", "package43", "package51", "package61")
    payload = {key: route.tolist() for key, route in zip(keys, routes)}
    payload["anchors"] = [list(anchor.point) for anchor in request.anchors]
    payload["nearby_triangles"] = nearby.tolist(); return payload


def _payload(root, fiber, request, snapshot, capture_ms, rows):
    p41_result, p43_result = rows["package41"][2][-1], rows["package43"][2][-1]
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "root": root.name, "fiber_id": fiber.id, "fiber_name": fiber.name,
            "triangles": len(snapshot.triangles), "colliders": snapshot.source_count,
            "capture_ms": capture_ms, "planner_route_delta": _route_delta(p41_result, p43_result),
            "v1": _v1_payload(rows["v1"][0], rows["v1"][2][-1], request, snapshot),
            "package41": _planner_payload(rows["package41"][0], p41_result, request, snapshot),
            "package43": _planner_payload(rows["package43"][0], p43_result, request, snapshot),
            "package51": _solver_payload(rows["package51"][0], rows["package51"][2], request, snapshot),
            "package61": _solver_payload(rows["package61"][0], rows["package61"][2], request, snapshot),
            "visual": _visual(request, rows, snapshot)}


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    started = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
    request = bench._request(root, fiber, anchors, colliders); capture_ms = 1000.0 * (perf_counter() - started)
    rows = _measure_all(_calls(root, fiber, depsgraph, request, snapshot), args.repeats)
    return _payload(root, fiber, request, snapshot, capture_ms, rows)


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    keys = ("v1", "package41", "package43", "package51", "package61")
    print("AF_V2_ACCEPTED", json.dumps({key: record[key]["timing"] for key in keys}), flush=True)


if __name__ == "__main__":
    main()
