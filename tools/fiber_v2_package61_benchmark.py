"""Read-only V1 / Package 5.1 / Package 6 / Package 6.1 benchmark."""

import argparse
import json
from pathlib import Path
import random
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import build_triangle_snapshot, solve_package51, solve_package6, solve_package61
from anthroforge.tools import fiber_v2_package5_benchmark as p5bench
from anthroforge.tools import fiber_v2_package6_benchmark as p6bench
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
            "package6": lambda: solve_package6(request, snapshot),
            "package61": lambda: solve_package61(request, snapshot)}


def _measure(calls, repeats):
    rows = {key: [] for key in calls}; times = {key: [] for key in calls}; rng = random.Random(6106)
    for call in calls.values(): call()
    for _index in range(max(1, repeats)):
        order = list(calls); rng.shuffle(order); _measure_order(order, calls, rows, times)
    return rows, times


def _measure_order(order, calls, rows, times):
    for key in order:
        started = perf_counter(); rows[key].append(calls[key]())
        times[key].append(1000.0 * (perf_counter() - started))


def _p61_payload(times, rows, request, snapshot):
    output = p6bench._solver_payload(times, rows, request, snapshot)
    dispatch = [row.trace.dispatch_ms for row in rows]; modes = [row.trace.selected_mode for row in rows]
    output["dispatch_timing"] = p5bench._summary(dispatch); output["selected_mode"] = modes[-1]
    output["dispatch_stable"] = len(set(modes)) == 1
    output["dispatch_share_percent"] = 100.0 * output["dispatch_timing"]["median_ms"] / max(output["timing"]["median_ms"], 1e-12)
    return output


def _visual(source, v1, p51, p6, p61, snapshot):
    planner = np.asarray(p51.planner.reference); routes = tuple(map(np.asarray, (
        source, v1, planner, p51.result.points, p6.result.points, p61.result.points)))
    nearby = p41._nearby_faces(snapshot, routes)
    keys = ("source", "v1", "package43", "package51", "package6", "package61")
    output = {key: value.tolist() for key, value in zip(keys, routes)}
    output["nearby_triangles"] = nearby.tolist(); return output


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    started = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); capture = 1000.0 * (perf_counter() - started)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph); request = bench._request(root, fiber, anchors, colliders)
    rows, times = _measure(_calls(root, fiber, depsgraph, request, snapshot), args.repeats)
    return _payload(root, fiber, request, snapshot, capture, rows, times)


def _payload(root, fiber, request, snapshot, capture, rows, times):
    source = tuple(anchor.point for anchor in request.anchors); p51, p6, p61 = (rows[key][-1] for key in ("package51", "package6", "package61"))
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath), "root": root.name,
            "fiber_id": fiber.id, "fiber_name": fiber.name, "triangles": len(snapshot.triangles),
            "colliders": snapshot.source_count, "snapshot_capture_ms": capture, "repeats": len(times["v1"]),
            "v1": p5bench._v1_payload(times["v1"], rows["v1"][-1], request, snapshot),
            "package51": p6bench._solver_payload(times["package51"], rows["package51"], request, snapshot),
            "package6": p6bench._solver_payload(times["package6"], rows["package6"], request, snapshot),
            "package61": _p61_payload(times["package61"], rows["package61"], request, snapshot),
            "visual": _visual(source, rows["v1"][-1], p51, p6, p61, snapshot)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    keys = ("v1", "package51", "package6", "package61")
    print("AF_V2_PACKAGE61", json.dumps({key: record[key]["timing"] for key in keys}), flush=True)


if __name__ == "__main__":
    main()
