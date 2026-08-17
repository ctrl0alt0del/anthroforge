"""Read-only V1 / Package 5.1 / 6.1 / 8 / 8.1 benchmark."""

import argparse
import json
from pathlib import Path
import random
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot, solve_package51,
                                     solve_package61, solve_package8, solve_package81)
from anthroforge.tools import fiber_v2_package5_benchmark as p5bench
from anthroforge.tools import fiber_v2_package6_benchmark as p6bench
from anthroforge.tools import fiber_v2_package8_benchmark as p8bench
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--contact-weight", type=float, default=10.0); parser.add_argument("--samples", type=int, default=5)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _sample_factors(count):
    return tuple(float(value) for value in np.linspace(0.1, 0.9, int(count)))


def _calls(root, fiber, depsgraph, request, snapshot, weight, factors):
    return {"v1": lambda: p5bench._v1_solve(root, fiber, depsgraph),
            "package51": lambda: solve_package51(request, snapshot),
            "package61": lambda: solve_package61(request, snapshot),
            "package8": lambda: solve_package8(request, snapshot, weight),
            "package81": lambda: solve_package81(request, snapshot, weight, factors)}


def _measure(calls, repeats):
    rows = {key: [] for key in calls}; times = {key: [] for key in calls}; rng = random.Random(8108)
    for call in calls.values():
        call()
    for _index in range(max(1, repeats)):
        order = list(calls); rng.shuffle(order); _measure_order(order, calls, rows, times)
    return rows, times


def _measure_order(order, calls, rows, times):
    for key in order:
        started = perf_counter(); rows[key].append(calls[key]())
        times[key].append(1000.0 * (perf_counter() - started))


def _solver_payload(times, rows, request, snapshot):
    output = p8bench._solver_payload(times, rows, request, snapshot); trace = rows[-1].trace
    output["sample_factors"] = trace.sample_factors; output["contact_query_rows"] = trace.contact_query_rows
    output["sample_contact_counts"] = trace.sample_contact_counts
    output["distinct_blocker_counts"] = trace.distinct_blocker_counts
    return output


def _visual(v1, p51, p61, p8, p81, snapshot):
    routes = tuple(map(np.asarray, (v1, p51.result.points, p61.result.points,
                                   p8.result.points, p81.result.points)))
    nearby = p41._nearby_faces(snapshot, routes)
    keys = ("v1", "package51", "package61", "package8", "package81")
    output = {key: value.tolist() for key, value in zip(keys, routes)}
    output["nearby_triangles"] = nearby.tolist(); return output


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    started = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); capture = 1000.0 * (perf_counter() - started)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph); request = bench._request(root, fiber, anchors, colliders)
    factors = _sample_factors(args.samples); calls = _calls(root, fiber, depsgraph, request, snapshot, args.contact_weight, factors)
    rows, times = _measure(calls, args.repeats); return _payload(root, fiber, request, snapshot, capture, rows, times)


def _payload(root, fiber, request, snapshot, capture, rows, times):
    p51, p61, p8, p81 = (rows[key][-1] for key in ("package51", "package61", "package8", "package81"))
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath), "root": root.name,
            "fiber_id": fiber.id, "fiber_name": fiber.name, "triangles": len(snapshot.triangles),
            "colliders": snapshot.source_count, "snapshot_capture_ms": capture, "repeats": len(times["v1"]),
            "v1": p5bench._v1_payload(times["v1"], rows["v1"][-1], request, snapshot),
            "package51": p6bench._solver_payload(times["package51"], rows["package51"], request, snapshot),
            "package61": p6bench._solver_payload(times["package61"], rows["package61"], request, snapshot),
            "package8": p8bench._solver_payload(times["package8"], rows["package8"], request, snapshot),
            "package81": _solver_payload(times["package81"], rows["package81"], request, snapshot),
            "visual": _visual(rows["v1"][-1], p51, p61, p8, p81, snapshot)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    keys = ("v1", "package51", "package61", "package8", "package81")
    print("AF_V2_PACKAGE81", json.dumps({key: record[key]["timing"] for key in keys}), flush=True)


if __name__ == "__main__":
    main()
