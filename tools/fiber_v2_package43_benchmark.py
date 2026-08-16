"""Read-only V1/Package 4.x benchmark for the fused-native Package 4.3 experiment."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (plan_reference, plan_reference_v41,
                                     plan_reference_v42, plan_reference_v43)
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=5)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _calls(request, snapshot):
    return (("package4", lambda: plan_reference(request, snapshot)),
            ("package41", lambda: plan_reference_v41(request, snapshot)),
            ("package42", lambda: plan_reference_v42(request, snapshot)),
            ("package43", lambda: plan_reference_v43(request, snapshot)))


def _timed_planners(request, snapshot, repeats):
    calls = _calls(request, snapshot); times = {name: [] for name, _call in calls}
    values = {name: [] for name, _call in calls}
    for repeat in range(repeats):
        for name, call in calls[repeat % len(calls):] + calls[:repeat % len(calls)]:
            started = perf_counter(); values[name].append(call())
            times[name].append(1000.0 * (perf_counter() - started))
    return times, values


def _planner_payload(times, values, snapshot, request):
    result = values[-1]; validation = p41._validated(result, snapshot, request)
    return bench._v2_payload(times, result, validation, bench._deterministic(values))


def _planner_rows(times, values, snapshot, request):
    return {name: _planner_payload(times[name], values[name], snapshot, request) for name in times}


def _comparisons(values):
    reference = values["package41"][-1]
    return {name: p41._comparison(reference, rows[-1]) for name, rows in values.items()}


def _visual(source, v1, values, snapshot):
    routes = {name: list(rows[-1].reference) for name, rows in values.items()}
    nearby = p41._nearby_faces(snapshot, (source, v1.points, *routes.values()))
    return {"source": np.asarray(source).tolist(), "v1": np.asarray(v1.points).tolist(),
            "routes": routes, "nearby_triangles": nearby.tolist()}


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); colliders, snapshot, capture = p41._capture(root, depsgraph)
    anchors, legacy = bench._open_anchors(root, fiber, depsgraph)
    request = bench._request(root, fiber, anchors, colliders); _warm(request, snapshot)
    v1_times, v1_values = bench._timed(lambda: bench._v1_plan(root, fiber, legacy, depsgraph), args.repeats)
    times, values = _timed_planners(request, snapshot, args.repeats)
    return _payload(root, fiber, request, snapshot, capture, v1_times, v1_values, times, values)


def _warm(request, snapshot):
    for _name, call in _calls(request, snapshot):
        call()


def _payload(root, fiber, request, snapshot, capture, v1_times, v1_values, times, values):
    v1 = v1_values[-1]; radius = request.collision_policy.collision_radius
    strict = bench._strict_validation(np.asarray(v1.points), request.anchors, snapshot,
                                      radius, request.tolerances.clearance_slack)
    source = tuple(anchor.point for anchor in request.anchors)
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "fiber_id": fiber.id, "triangles": len(snapshot.triangles), "snapshot_capture_ms": capture,
            "v1": bench._v1_payload(v1_times, v1, strict),
            "planners": _planner_rows(times, values, snapshot, request),
            "comparison_to_41": _comparisons(values), "visual": _visual(source, v1, values, snapshot)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: row["timing"] | {"termination": row["termination"]} for name, row in record["planners"].items()}
    print("AF_V2_PACKAGE43", json.dumps({"v1": record["v1"]["timing"], "planners": summary}), flush=True)


if __name__ == "__main__":
    main()
