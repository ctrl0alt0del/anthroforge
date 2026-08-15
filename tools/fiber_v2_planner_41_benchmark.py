"""Read-only V1 versus Package 4 versus Package 4.1 Blender benchmark."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot, plan_reference,
                                     plan_reference_v41, validate_static_clearance)
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _paired(request, snapshot, repeats):
    calls = (("package4", lambda: plan_reference(request, snapshot)),
             ("package41", lambda: plan_reference_v41(request, snapshot)))
    times, values = {name: [] for name, _call in calls}, {name: [] for name, _call in calls}
    for index in range(repeats):
        for name, call in calls[index % 2:] + calls[:index % 2]:
            started = perf_counter(); values[name].append(call())
            times[name].append(1000.0 * (perf_counter() - started))
    return times, values


def _capture(root, depsgraph):
    started = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders)
    return colliders, snapshot, 1000.0 * (perf_counter() - started)


def _validated(result, snapshot, request):
    if len(result.reference) < 2:
        return None
    radius = request.collision_policy.collision_radius
    return validate_static_clearance(result.reference, snapshot, radius, result.contacts,
                                     slack=request.tolerances.clearance_slack)


def _comparison(old, new):
    first, second = np.asarray(old.reference), np.asarray(new.reference)
    delta = float(np.max(np.abs(first - second))) if first.shape == second.shape and len(first) else float("inf")
    return {"same_termination": old.termination is new.termination, "same_mode": old.mode is new.mode,
            "same_count": first.shape == second.shape, "max_reference_delta": delta,
            "same_corridor": old.corridor == new.corridor}


def _nearby_faces(snapshot, routes):
    points = np.vstack([np.asarray(row) for row in routes if len(row)])
    pad = max(float(np.linalg.norm(np.ptp(points, axis=0))) * .15, .05)
    low, high = points.min(axis=0) - pad, points.max(axis=0) + pad
    faces = snapshot.vertices[snapshot.triangles]
    ids = np.flatnonzero(np.all(faces.max(1) >= low, axis=1) & np.all(faces.min(1) <= high, axis=1))
    return faces[ids if len(ids) <= 5000 else ids[np.linspace(0, len(ids) - 1, 5000).astype(int)]]


def _visual(snapshot, source, v1, old, new):
    routes = (source, v1.points, old.reference, new.reference)
    return {"source": np.asarray(source).tolist(), "v1": np.asarray(v1.points).tolist(),
            "package4": list(old.reference), "package41": list(new.reference),
            "anchors": [list(anchor) for anchor in source],
            "nearby_triangles": _nearby_faces(snapshot, routes).tolist()}


def _v2_payload(times, values, snapshot, request):
    result = values[-1]; validation = _validated(result, snapshot, request)
    return bench._v2_payload(times, result, validation, bench._deterministic(values))


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders, snapshot, capture_ms = _capture(root, depsgraph)
    anchors, legacy = bench._open_anchors(root, fiber, depsgraph); request = bench._request(root, fiber, anchors, colliders)
    bench._v1_plan(root, fiber, legacy, depsgraph); plan_reference(request, snapshot); plan_reference_v41(request, snapshot)
    v1_times, v1_values = bench._timed(lambda: bench._v1_plan(root, fiber, legacy, depsgraph), args.repeats)
    times, values = _paired(request, snapshot, args.repeats)
    return _payload(root, fiber, request, snapshot, capture_ms, v1_times, v1_values, times, values)


def _payload(root, fiber, request, snapshot, capture_ms, v1_times, v1_values, times, values):
    old, new, v1 = values["package4"][-1], values["package41"][-1], v1_values[-1]
    radius, slack = request.collision_policy.collision_radius, request.tolerances.clearance_slack
    v1_validation = bench._strict_validation(np.asarray(v1.points), request.anchors, snapshot, radius, slack)
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "fiber_id": fiber.id, "triangles": len(snapshot.triangles), "snapshot_capture_ms": capture_ms,
            "v1": bench._v1_payload(v1_times, v1, v1_validation),
            "package4": _v2_payload(times["package4"], values["package4"], snapshot, request),
            "package41": _v2_payload(times["package41"], values["package41"], snapshot, request),
            "comparison": _comparison(old, new),
            "visual": _visual(snapshot, tuple(anchor.point for anchor in request.anchors), v1, old, new)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PLANNER_41", json.dumps({key: record[key] for key in ("v1", "package4", "package41", "comparison")}), flush=True)


if __name__ == "__main__":
    main()
