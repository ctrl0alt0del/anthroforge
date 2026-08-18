"""Benchmark production V2.4 against V2.5 branch-2 on one Blender Fiber."""

import json
from pathlib import Path
from statistics import median
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (clear_v24_route_cache, solve_v24,
                                     solve_v25_branch2)
from anthroforge.tools import fiber_v25_branch2_sweep as base


def _timed(solver, request, snapshot):
    started = perf_counter(); package = solver(request, snapshot)
    return 1000.0 * (perf_counter() - started), package


def _measure(solver, request, snapshot):
    clear_v24_route_cache(); rows = [_timed(solver, request, snapshot) for _index in range(9)]
    package = rows[-1][1]
    return {"cold_ms": rows[0][0], "warm_median_ms": median(row[0] for row in rows[1:]),
            "termination": package.result.termination.value,
            "validated": package.result.validated, "planner_mode": package.result.route_branch,
            "metrics": base._metrics(package.result.points),
            "trace": vars(package.trace), "points": package.result.points}


def _spans(planner):
    return [{"first_edge": row.first_edge, "edge_count": row.edge_count,
             "branch": row.branch.value, "owner_id": row.owner_id,
             "lift_factor": row.lift_factor, "start_anchor": row.start_anchor,
             "end_anchor": row.end_anchor} for row in planner.spans]


def _summary(record):
    return {name: {key: value for key, value in record[name].items() if key != "points"}
            for name in ("v24", "v25_branch2")}


def _visual(root, fiber, planner, old, new, snapshot):
    best = {"points": new["points"]}
    baseline = type("Package", (), {"result": type("Result", (), {"points": old["points"]})()})()
    return base._visual(root, fiber, planner, baseline, best, snapshot)


def _record(args):
    root = base.common._root(); fiber = base.common._fiber(root, args.fiber_id)
    request, snapshot, anchors = base._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    old = _measure(solve_v24, request, snapshot); new = _measure(solve_v25_branch2, request, snapshot)
    clear_v24_route_cache(); planner = solve_v24(request, snapshot).planner
    return {"file": bpy.data.filepath, "file_sha256": base.common._file_hash(bpy.data.filepath),
            "fiber": fiber.id, "anchors": [list(row.point) for row in anchors],
            "planner_metrics": base._metrics(planner.reference), "spans": _spans(planner),
            "v24": old, "v25_branch2": new,
            "visual": _visual(root, fiber, planner, old, new, snapshot)}


def main():
    base._ensure_addon(); args = base._args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V25_BRANCH2 " + json.dumps({"fiber": record["fiber"],
          **_summary(record)}, default=str), flush=True)


if __name__ == "__main__":
    main()
