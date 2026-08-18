"""Benchmark V2.4 against collision-safe hard-pin smoothing."""

import argparse
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from types import SimpleNamespace

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (clear_v24_route_cache, solve_pin_smoothing,
                                     solve_v24)
from anthroforge.core.vcp.v2.collision import cached_native_collision_world
from anthroforge.core.vcp.v2 import solver_pin_smoothing as smoothing_impl
from anthroforge.tools import fiber_v25_branch2_sweep as base


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--fiber-id", default="FIBER_2")
    parser.add_argument("--solver", choices=("both", "v24", "pin"), default="both")
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--retraction-factors", default="2,1.5")
    parser.add_argument("--fuse-second-stage", choices=("yes", "no"), default="yes")
    parser.add_argument("--fused-strength", type=float, default=3.0)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _timed(solver, request, snapshot):
    started = perf_counter(); package = solver(request, snapshot)
    return 1000.0 * (perf_counter() - started), package


def _measure(solver, request, snapshot, repeats=9):
    clear_v24_route_cache(); rows = [_timed(solver, request, snapshot) for _index in range(repeats)]
    package = rows[-1][1]; warm = tuple(row[0] for row in rows[1:])
    return {"cold_ms": rows[0][0], "warm_ms": warm, "warm_median_ms": median(warm),
            "termination": package.result.termination.value, "validated": package.result.validated,
            "metrics": base._metrics(package.result.points), "trace": vars(package.trace),
            "points": package.result.points}


def _record(args):
    _configure(args)
    root = base.common._root(); fiber = base.common._fiber(root, args.fiber_id)
    started = perf_counter(); request, snapshot, anchors = base._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    capture_ms = 1000.0 * (perf_counter() - started); rows = _solver_rows(args, request, snapshot)
    stored = base._source(root, fiber); planner = solve_v24(request, snapshot).planner
    record = {"file": bpy.data.filepath, "file_sha256": base.common._file_hash(bpy.data.filepath),
            "fiber": fiber.id, "capture_ms": capture_ms,
            "anchors": [list(row.point) for row in anchors],
            "request": _request_rows(request, planner), **rows,
            "stored_v1": {"metrics": base._metrics(stored), "points": stored}}
    if args.solver == "both":
        record["visual"] = _visual(root, fiber, planner, rows, snapshot)
        record["owner_distance"] = _owner_distance(request, record["visual"])
    return record


def _configure(args):
    smoothing_impl.RETRACTION_FACTORS = _factors(args.retraction_factors)
    smoothing_impl.FUSE_SECOND_STAGE = args.fuse_second_stage == "yes"
    smoothing_impl.FUSED_SMOOTH_STRENGTH = float(args.fused_strength)


def _factors(value):
    return tuple(float(row.strip()) for row in str(value).split(",") if row.strip())


def _solver_rows(args, request, snapshot):
    rows = {}
    if args.solver in ("both", "v24"):
        rows["v24"] = _measure(solve_v24, request, snapshot, args.repeats)
    if args.solver in ("both", "pin"):
        rows["pin_smoothing"] = _measure(solve_pin_smoothing, request, snapshot, args.repeats)
    return rows


def _request_rows(request, planner):
    owners = [row.owner_id for row in request.anchors]
    return {"owners": owners, "pin_indices": planner.pin_indices,
            "contacts": [vars(row) for row in planner.contacts],
            "spans": [_span(row) for row in planner.spans], "point_count": len(planner.reference)}


def _span(row):
    return {"first_edge": row.first_edge, "edge_count": row.edge_count,
            "branch": row.branch.value, "owner_id": row.owner_id,
            "lift_factor": row.lift_factor, "start_anchor": row.start_anchor,
            "end_anchor": row.end_anchor}


def _visual(root, fiber, planner, rows, snapshot):
    baseline = SimpleNamespace(result=SimpleNamespace(points=rows["v24"]["points"]))
    best = {"points": rows["pin_smoothing"]["points"]}
    return base._visual(root, fiber, planner, baseline, best, snapshot)


def _owner_distance(request, visual):
    owners = {row.owner_id for row in request.anchors if row.owner_id}
    if len(owners) != 1:
        return {}
    owner = next(iter(owners)); colliders = tuple(row for row in request.colliders if row.owner_id == owner)
    world = cached_native_collision_world(colliders)
    return {name: _distance_metrics(world, visual[name]) for name in ("source", "planner", "v24", "v25")}


def _distance_metrics(world, points):
    values = np.asarray(points, dtype=np.float64)
    _closest, _normals, distances, _ids, _inside = world.nearest(values)
    return {"maximum": float(np.max(distances)), "p95": float(np.percentile(distances, 95.0)),
            "mean": float(np.mean(distances))}


def _summary(record):
    names = tuple(name for name in ("v24", "pin_smoothing") if name in record)
    return {name: {key: value for key, value in record[name].items() if key != "points"} for name in names}


def main():
    base._ensure_addon(); args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_PIN_SMOOTHING " + json.dumps({"fiber": record["fiber"], **_summary(record)}), flush=True)


if __name__ == "__main__":
    main()
