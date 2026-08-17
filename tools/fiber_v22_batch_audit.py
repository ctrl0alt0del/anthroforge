"""Read-only shared-capture V1/V2.2 batch audit on a loaded blend."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy

from anthroforge.core.vcp.v2 import (clear_native_collision_world_cache,
    clear_structural_cache, clear_triangle_snapshot_cache, clear_v22_route_cache,
    solve_v22, triangle_snapshot_cache_stats)
from anthroforge.tools import fiber_v22_benchmark as v22b
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _root():
    return next(obj for obj in bpy.context.scene.objects
                if obj.get("anthroforge_root") and len(obj.af_vcp_system.fibers))


def _request_row(root, fiber, depsgraph, colliders):
    try:
        anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
        return fiber, bench._request(root, fiber, anchors, colliders), ""
    except Exception as exc:
        return fiber, None, str(exc)


def _capture(root):
    depsgraph = bpy.context.evaluated_depsgraph_get(); started = perf_counter()
    colliders, digest_ms = v22b._colliders(bpy.context.scene, root, depsgraph)
    rows = [_request_row(root, fiber, depsgraph, colliders)
            for fiber in root.af_vcp_system.fibers]
    return rows, depsgraph, digest_ms, 1000.0 * (perf_counter() - started)


def _v1_batch(root, rows, depsgraph):
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    solver, output, started = FiberSolver(), [], perf_counter(); solver.clear_cache()
    for fiber, _request, error in rows:
        tick = perf_counter(); points = () if error else solver.solve_points(
            root, fiber, bpy.context.scene, depsgraph, bake=False)
        output.append({"fiber": fiber.id, "ms": _ms(tick), "points": len(points), "error": error})
    return output, _ms(started)


def _v22_batch(rows):
    output, started = [], perf_counter()
    for fiber, request, error in rows:
        tick = perf_counter(); result = None if error else solve_v22(request)
        output.append(_v22_row(fiber, result, error, _ms(tick)))
    return output, _ms(started)


def _v22_row(fiber, result, error, elapsed):
    if result is None:
        return {"fiber": fiber.id, "ms": elapsed, "error": error}
    solved = result.result
    return {"fiber": fiber.id, "ms": elapsed, "termination": solved.termination.value,
            "valid": solved.validated, "points": len(solved.points),
            "message": solved.message, "error": error}


def _ms(started):
    return 1000.0 * (perf_counter() - started)


def _clear_v22():
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache()
    clear_structural_cache(); clear_v22_route_cache()


def _record():
    root = _root(); rows, depsgraph, digest_ms, capture_ms = _capture(root)
    v1, v1_ms = _v1_batch(root, rows, depsgraph); _clear_v22()
    cold, cold_ms = _v22_batch(rows); cold_cache = triangle_snapshot_cache_stats()
    warm, warm_ms = _v22_batch(rows); warm_cache = triangle_snapshot_cache_stats()
    return {"file": bpy.data.filepath, "fibers": len(rows), "capture_ms": capture_ms,
            "digest_ms": digest_ms, "v1_ms": v1_ms, "v1": v1,
            "v22_cold_ms": cold_ms, "v22_cold": cold, "cold_cache": cold_cache,
            "v22_warm_ms": warm_ms, "v22_warm": warm, "warm_cache": warm_cache}


def main():
    args, record = _args(), _record(); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V22_BATCH", json.dumps({key: record[key] for key in
          ("fibers", "capture_ms", "v1_ms", "v22_cold_ms", "v22_warm_ms")}), flush=True)


if __name__ == "__main__":
    main()
