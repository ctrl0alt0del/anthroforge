"""Compare V2.4 and guarded pin smoothing for every open Fiber."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import solve_pin_smoothing, solve_v24
from anthroforge.tools import fiber_pin_smoothing_benchmark as benchmark
from anthroforge.tools import fiber_v24_visual_audit as audit
from anthroforge.tools import fiber_v25_branch2_sweep as base
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _timed(solver, request, snapshot):
    started = perf_counter(); value = solver(request, snapshot)
    return 1000.0 * (perf_counter() - started), value


def _pins(package, anchors):
    points = np.asarray(package.result.points); indices = np.asarray(package.planner.pin_indices, dtype=np.int64)
    targets = np.asarray([row.point for row in anchors]); return float(np.max(np.linalg.norm(points[indices] - targets, axis=1)))


def _result(elapsed, package, anchors):
    trace = package.trace
    return {"ms": elapsed, "validated": package.result.validated,
            "termination": package.result.termination.value, "metrics": base._metrics(package.result.points),
            "pin_error": _pins(package, anchors), "points": package.result.points,
            "surface_attempts": int(getattr(trace, "surface_tangent_attempts", 0)),
            "surface_accepted": int(getattr(trace, "surface_tangent_accepted", 0)),
            "global_attempts": int(getattr(trace, "global_pin_attempts", 0)),
            "global_accepted": int(getattr(trace, "global_pin_accepted", 0)),
            "retraction_accepted": bool(getattr(trace, "retraction_accepted", False))}


def _row(root, fiber, depsgraph, colliders, snapshot):
    try:
        anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
        request = common._request(root, fiber, anchors, colliders)
        old_ms, old = _timed(solve_v24, request, snapshot); new_ms, new = _timed(solve_pin_smoothing, request, snapshot)
        return {"fiber": fiber.id, "v24": _result(old_ms, old, anchors), "guarded": _result(new_ms, new, anchors),
                "delta": audit._delta(old.result.points, new.result.points)}
    except Exception as error:
        return {"fiber": fiber.id, "error": str(error)}


def _record():
    root = common._root(); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders, _capture = audit._colliders(root, depsgraph); key = audit._snapshot_key(root, colliders)
    world = audit.cached_native_collision_world_batch(colliders, key)
    snapshot = audit.build_triangle_snapshot_known(colliders, world.closed_flags)
    rows = [_row(root, fiber, depsgraph, colliders, snapshot) for fiber in root.af_vcp_system.fibers]
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath), "fibers": rows}


def _summary(record):
    rows = [row for row in record["fibers"] if "error" not in row]
    return {"count": len(rows), "valid": sum(row["guarded"]["validated"] for row in rows),
            "changed": sum((row["delta"]["max"] or 0.0) > 1.0e-9 for row in rows),
            "surface_accepted": sum(row["guarded"]["surface_accepted"] for row in rows),
            "global_accepted": sum(row["guarded"]["global_accepted"] for row in rows)}


def main():
    benchmark.base._ensure_addon(); args = _args(); record = _record(); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_PIN_AUDIT " + json.dumps(_summary(record)), flush=True)


if __name__ == "__main__":
    main()
