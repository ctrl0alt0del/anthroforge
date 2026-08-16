"""Read-only randomized V1 / Package 5.1 / Package 6 benchmark."""

import argparse
import json
from pathlib import Path
import random
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import build_triangle_snapshot, solve_package51, solve_package6
from anthroforge.tools import fiber_v2_package5_benchmark as p5bench
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=7)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _calls(root, fiber, depsgraph, request, snapshot):
    return {"v1": lambda: p5bench._v1_solve(root, fiber, depsgraph),
            "package51": lambda: solve_package51(request, snapshot),
            "package6": lambda: solve_package6(request, snapshot)}


def _measure(calls, repeats):
    rows = {key: [] for key in calls}; times = {key: [] for key in calls}; rng = random.Random(6006)
    for call in calls.values():
        call()
    for _index in range(max(1, repeats)):
        order = list(calls); rng.shuffle(order); _measure_order(order, calls, rows, times)
    return rows, times


def _measure_order(order, calls, rows, times):
    for key in order:
        started = perf_counter(); rows[key].append(calls[key]())
        times[key].append(1000.0 * (perf_counter() - started))


def _visual(source, v1, p51, p6, snapshot):
    planner = np.asarray(p51.planner.reference); optimized = np.asarray(p51.result.points)
    trusted = np.asarray(p6.result.points); routes = tuple(map(np.asarray, (source, v1, planner, optimized, trusted)))
    nearby = p41._nearby_faces(snapshot, routes)
    return {"source": routes[0].tolist(), "v1": routes[1].tolist(), "package43": planner.tolist(),
            "package51": optimized.tolist(), "package6": trusted.tolist(), "nearby_triangles": nearby.tolist()}


def _quality(item, request):
    points = np.asarray(item.result.points); delta = np.diff(points, axis=0)
    curve = float(np.linalg.norm(delta, axis=1).sum())
    bend = float(np.linalg.norm(np.diff(points, n=2, axis=0), axis=1).sum())
    pins = [np.linalg.norm(points[index] - anchor.point)
            for index, anchor in zip(item.planner.pin_indices, request.anchors)]
    return {"path_length": curve, "discrete_curvature": bend, "max_pin_error": max(pins, default=0.0)}


def _solver_payload(times, rows, request, snapshot):
    output = p5bench._p5_payload(times, rows, request, snapshot)
    output["quality"] = _quality(rows[-1], request); return output


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    capture = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); capture_ms = 1000.0 * (perf_counter() - capture)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph); request = bench._request(root, fiber, anchors, colliders)
    rows, times = _measure(_calls(root, fiber, depsgraph, request, snapshot), args.repeats)
    return _payload(root, fiber, request, snapshot, capture_ms, rows, times)


def _payload(root, fiber, request, snapshot, capture, rows, times):
    source = tuple(anchor.point for anchor in request.anchors); p51, p6 = rows["package51"][-1], rows["package6"][-1]
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath), "root": root.name,
            "fiber_id": fiber.id, "fiber_name": fiber.name, "triangles": len(snapshot.triangles),
            "colliders": snapshot.source_count, "snapshot_capture_ms": capture, "repeats": len(times["v1"]),
            "route_policy": {"surface_routing": bool(fiber.use_surface_routing),
                             "segment_collisions": bool(fiber.use_segment_collisions)},
            "v1": p5bench._v1_payload(times["v1"], rows["v1"][-1], request, snapshot),
            "package51": _solver_payload(times["package51"], rows["package51"], request, snapshot),
            "package6": _solver_payload(times["package6"], rows["package6"], request, snapshot),
            "visual": _visual(source, rows["v1"][-1], p51, p6, snapshot)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PACKAGE6", json.dumps({key: record[key]["timing"] for key in ("v1", "package51", "package6")}), flush=True)


if __name__ == "__main__":
    main()
