"""Measure real Blender capture and production-3 progressive slices read-only."""

import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
from statistics import median
import sys
from time import perf_counter

import bpy

from anthroforge.core.vcp.fiber_engine_registry import selection_for_fiber
from anthroforge.core.vcp.fiber_v2_runtime import begin_v2_runtime
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--budget-ms", type=float, default=12.0)
    parser.add_argument("--profile", action="store_true")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _step(session, budget):
    started = perf_counter(); result = session.step(budget)
    return {"ms": 1000.0 * (perf_counter() - started), "phase": session.phase,
            "done": result.done, "display": result.display_mode}


def _summary(rows):
    times = sorted(row["ms"] for row in rows); rank = max(0, int(.95 * len(times) + .999) - 1)
    return {"count": len(times), "p50_ms": median(times), "p95_ms": times[rank],
            "max_ms": max(times), "over_20_ms": sum(value > 20.0 for value in times)}


def _begin(root, fiber):
    started = perf_counter(); solver = register_fiber_sync()._solver; scene = bpy.context.scene
    session = begin_v2_runtime(solver, root, fiber, scene,
                               bpy.context.evaluated_depsgraph_get(), "INTERACTIVE",
                               selection_for_fiber(fiber, "V2"))
    return session, 1000.0 * (perf_counter() - started)


def _result_details(session):
    result = session.result(); diagnostics = getattr(result, "diagnostics", None)
    trace = None if session.package is None else session.package.trace
    return {"termination": result.termination_reason, "validated": result.validated,
            "source_colliders": len(session.source_colliders), "captured_colliders": len(session.colliders),
            "triangles": sum(len(row.triangles) for row in session.colliders),
            "core_total_ms": 0.0 if trace is None else trace.total_ms,
            "planner_ms": 0.0 if trace is None else trace.planner_ms,
            "diagnostics": {} if diagnostics is None else vars(diagnostics)}


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    with suppress_vcp_prop_updates(): fiber.preview_planner_route = False
    session, initialization = _begin(root, fiber)
    rows = _run_steps(session, args.budget_ms, args.profile)
    return {"file": bpy.data.filepath, "fiber": fiber.id, "initialization_ms": initialization,
        "slices": rows, "summary": _summary(rows), **_result_details(session),
        "source_sha256": common._file_hash(bpy.data.filepath)}


def _run_steps(session, budget, profile):
    profiler = cProfile.Profile() if profile else None; rows = []
    if profiler: profiler.enable()
    while not session.done and len(rows) < 10000: rows.append(_step(session, budget))
    if profiler: profiler.disable(); _print_profile(profiler)
    return rows


def _print_profile(profiler):
    output = io.StringIO(); stats = pstats.Stats(profiler, stream=output).sort_stats("cumtime")
    stats.print_stats(35); print(output.getvalue(), flush=True)


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2))
    print("AF_V2_P3_SLICE", json.dumps({"fiber": record["fiber"], **record["summary"]}), flush=True)


if __name__ == "__main__":
    main()
