"""Profile V2.2 cold capture and acceleration construction on a loaded blend."""

import argparse
import cProfile
import json
from pathlib import Path
import pstats
import sys
from time import perf_counter

import bpy

from anthroforge.core.vcp.v2 import (cached_native_collision_world,
    cached_triangle_snapshot, clear_native_collision_world_cache,
    clear_structural_cache, clear_triangle_snapshot_cache, clear_v22_route_cache,
    solve_v22, v22_request_signature, v22_snapshot_key)
from anthroforge.tools import fiber_v22_benchmark as bench
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True); parser.add_argument("--fiber-id", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _clear():
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache()
    clear_structural_cache(); clear_v22_route_cache()


def _timed(call):
    started = perf_counter(); value = call()
    return value, 1000.0 * (perf_counter() - started)


def _capture(fiber_id):
    root = common._root(); fiber = common._fiber(root, fiber_id)
    depsgraph, depsgraph_ms = _timed(bpy.context.evaluated_depsgraph_get)
    colliders, collider_ms = _timed(lambda: bench._colliders(bpy.context.scene, root, depsgraph))
    anchors, anchor_ms = _timed(lambda: common._open_anchors(root, fiber, depsgraph)[0])
    request, request_ms = _timed(lambda: common._request(root, fiber, anchors, colliders[0]))
    return request, {"depsgraph_ms": depsgraph_ms, "collider_ms": collider_ms,
                     "digest_ms": colliders[1], "anchor_ms": anchor_ms, "request_ms": request_ms}


def _build_costs(request):
    _clear(); key = v22_snapshot_key(request)
    _signature, signature_ms = _timed(lambda: v22_request_signature(request))
    _snapshot, snapshot_ms = _timed(lambda: cached_triangle_snapshot(request.colliders, key))
    _world, world_ms = _timed(lambda: cached_native_collision_world(request.colliders, key))
    return {"signature_ms": signature_ms, "triangle_snapshot_ms": snapshot_ms,
            "collision_world_ms": world_ms}


def _profile_once(request):
    _clear(); profiler = cProfile.Profile(); started = perf_counter(); profiler.enable()
    result = solve_v22(request); profiler.disable()
    return result, 1000.0 * (perf_counter() - started), _profile_rows(profiler)


def _cold_once(request):
    _clear(); result, elapsed = _timed(lambda: solve_v22(request))
    return result, elapsed


def _profile_capture():
    root = common._root(); depsgraph = bpy.context.evaluated_depsgraph_get()
    profiler = cProfile.Profile(); started = perf_counter(); profiler.enable()
    bench._colliders(bpy.context.scene, root, depsgraph); profiler.disable()
    return 1000.0 * (perf_counter() - started), _profile_rows(profiler, 25)


def _profile_rows(profiler, limit=40):
    stats = pstats.Stats(profiler); rows = []
    for (file, line, name), values in stats.stats.items():
        rows.append({"file": file, "line": line, "name": name, "calls": values[1],
                     "self_ms": 1000.0 * values[2], "cumulative_ms": 1000.0 * values[3]})
    return sorted(rows, key=lambda row: row["cumulative_ms"], reverse=True)[:limit]


def _result_row(result):
    solved = result.result; trace = result.trace
    return {"termination": solved.termination.value, "validated": solved.validated,
            "route": solved.route_branch, "trace": vars(trace)}


def _record(fiber_id):
    request, capture = _capture(fiber_id); builds = _build_costs(request)
    cold_result, cold_ms = _cold_once(request)
    result, wall_ms, profile = _profile_once(request)
    capture_profile_ms, capture_profile = _profile_capture()
    return {"file": bpy.data.filepath, "fiber": fiber_id, "capture": capture,
            "builds": builds, "cold_wall_ms": cold_ms, "cold_profiled_wall_ms": wall_ms,
            "result": _result_row(cold_result), "profiled_result": _result_row(result), "profile": profile,
            "capture_profiled_wall_ms": capture_profile_ms, "capture_profile": capture_profile}


def main():
    args = _args(); record = _record(args.fiber_id); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V22_COLD", json.dumps({"fiber": record["fiber"], "capture": record["capture"],
          "builds": record["builds"], "cold_ms": record["cold_wall_ms"],
          "profiled_ms": record["cold_profiled_wall_ms"]}), flush=True)


if __name__ == "__main__":
    main()
