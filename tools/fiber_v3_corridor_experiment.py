"""Read-only Blender benchmark for the isolated scalar-corridor V3 experiment."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2.production import solve_v2
from anthroforge.core.vcp.v3_covariant_experiment import solve_v3_covariant
from anthroforge.core.vcp.v3_active_step_experiment import solve_v3_active_refined, solve_v3_active_step
from anthroforge.core.vcp.v3_experiment import clear_v3_experiment_caches, solve_v3_corridor
from anthroforge.core.vcp.v3_joint_experiment import solve_v3_joint
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _timed(call):
    started = perf_counter(); value = call(); return value, 1000.0 * (perf_counter() - started)


def _cold(call):
    clear_v3_experiment_caches()
    return _timed(call)


def _turns(points, pins=()):
    values = np.asarray(points); first, second = np.diff(values, axis=0)[:-1], np.diff(values, axis=0)[1:]
    scale = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1)
    angles = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", first, second) / np.maximum(scale, 1e-12), -1, 1)))
    free = np.asarray([value for index, value in enumerate(angles, 1) if index not in set(pins)])
    return {"max": float(np.max(angles)), "p95": float(np.percentile(angles, 95)), "sum": float(np.sum(angles)),
            "free_max": float(np.max(free)) if len(free) else 0.0, "free_p95": float(np.percentile(free, 95)) if len(free) else 0.0}


def _path(points, pins=()):
    values = np.asarray(points); length = float(np.linalg.norm(np.diff(values, axis=0), axis=1).sum())
    return {"points": values.tolist(), "length": length, "turns": _turns(values, pins)}


def _result_payload(result, timing):
    pins = result.corridor.pin_indices
    return {"timing_ms": timing, "termination": result.termination, "message": result.message,
            "valid": result.valid, "objective": result.objective, "alpha_min": min(result.alpha),
            "alpha_max": max(result.alpha), "alpha": result.alpha, "path": _path(result.points, pins),
            "corridor": {"planner_reused": result.corridor.planner_reused,
                         "exact_route_hit": result.corridor.exact_route_hit},
            "trace": vars(result.trace)}


def _v2_payload(package, timing, pins=()):
    result = package.result
    return {"timing_ms": timing, "termination": result.termination.value,
            "valid": result.validated, "path": _path(result.points, pins), "trace": vars(package.trace)}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders = common._colliders(bpy.context.scene, root, depsgraph)
    snapshot = common.build_triangle_snapshot(colliders); anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
    request = common._request(root, fiber, anchors, colliders)
    settings = replace(request.settings, max_accepted_steps=args.steps)
    return root, fiber, snapshot, replace(request, settings=settings)


def _run(args, request, snapshot):
    cold, cold_ms = _cold(lambda: solve_v3_corridor(request, snapshot))
    covariant_rows = [_cold(lambda: solve_v3_covariant(request, snapshot)) for _ in range(args.repeats)]; covariant, covariant_ms = covariant_rows[-1]
    joint_rows = [_cold(lambda: solve_v3_joint(request, snapshot)) for _ in range(args.repeats)]; joint, joint_ms = joint_rows[-1]
    active_rows = [_cold(lambda: solve_v3_active_step(request, snapshot)) for _ in range(args.repeats)]; active, active_ms = active_rows[-1]
    refined_rows = [_cold(lambda: solve_v3_active_refined(request, snapshot)) for _ in range(args.repeats)]; refined, refined_ms = refined_rows[-1]
    clear_v3_experiment_caches(); solve_v3_corridor(request, snapshot)
    exact_rows = [_timed(lambda: solve_v3_corridor(request, snapshot)) for _ in range(args.repeats)]
    warm_rows = [_timed(lambda: solve_v3_corridor(request, snapshot, cold.points,
                                                   cold.corridor.signature, False)) for _ in range(args.repeats)]
    v2, v2_ms = _timed(lambda: solve_v2(request, snapshot))
    return (cold, cold_ms, covariant, covariant_ms, covariant_rows, joint, joint_ms,
            joint_rows, active, active_ms, active_rows, refined, refined_ms, refined_rows,
            exact_rows, warm_rows, v2, v2_ms)


def _record(args):
    _root, fiber, snapshot, request = _capture(args)
    rows = _run(args, request, snapshot)
    cold = rows[0]
    direct, roadmap = cold.corridor.direct, cold.corridor.roadmap
    pins = cold.corridor.pin_indices
    return _record_payload(args, fiber, snapshot, pins, direct, roadmap, rows)


def _record_payload(args, fiber, snapshot, pins, direct, roadmap, rows):
    cold, cold_ms, coupled, coupled_ms, coupled_rows = rows[:5]
    joint, joint_ms, joint_rows, active, active_ms, active_rows = rows[5:11]
    refined, refined_ms, refined_rows, exact_rows, warm_rows, v2, v2_ms = rows[11:]
    output = {"file": bpy.data.filepath, "sha256": common._file_hash(bpy.data.filepath),
              "fiber": fiber.id, "steps": args.steps, "pin_indices": pins,
              "direct": _path(direct, pins), "roadmap": _path(roadmap, pins)}
    output.update(_experiment_rows(cold, cold_ms, coupled, coupled_rows, joint, joint_rows, active, active_rows))
    output.update({"v3_active_refined": _result_payload(refined, refined_ms), "v3_active_refined_median_ms": statistics.median(row[1] for row in refined_rows)})
    output.update({
            "v3_exact": _result_payload(exact_rows[-1][0], [row[1] for row in exact_rows]),
            "v3_exact_median_ms": statistics.median(row[1] for row in exact_rows),
            "v3_warm": _result_payload(warm_rows[-1][0], [row[1] for row in warm_rows]),
            "v3_warm_median_ms": statistics.median(row[1] for row in warm_rows),
            "v2": _v2_payload(v2, v2_ms, pins), "nearby_triangles": _nearby(snapshot, direct, roadmap)})
    return output


def _experiment_rows(cold, cold_ms, coupled, coupled_rows, joint, joint_rows, active, active_rows):
    return {"v3_cold": _result_payload(cold, cold_ms),
            "v3_covariant": _result_payload(coupled, coupled_rows[-1][1]),
            "v3_covariant_median_ms": statistics.median(row[1] for row in coupled_rows),
            "v3_joint": _result_payload(joint, joint_rows[-1][1]),
            "v3_joint_median_ms": statistics.median(row[1] for row in joint_rows),
            "v3_active": _result_payload(active, active_rows[-1][1]),
            "v3_active_median_ms": statistics.median(row[1] for row in active_rows)}


def _nearby(snapshot, direct, roadmap):
    routes = np.vstack((np.asarray(direct), np.asarray(roadmap)))
    padding = max(0.05, 0.15 * float(np.linalg.norm(np.ptp(routes, axis=0))))
    low, high = routes.min(axis=0) - padding, routes.max(axis=0) + padding
    faces = snapshot.vertices[snapshot.triangles]
    selected = np.all(faces.max(axis=1) >= low, axis=1) & np.all(faces.min(axis=1) <= high, axis=1)
    return faces[selected].tolist()


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {key: value for key, value in record.items() if key not in ("direct", "roadmap", "nearby_triangles")}
    for row in summary.values():
        if isinstance(row, dict) and "path" in row: row["path"].pop("points", None)
    print("AF_V3 " + json.dumps(summary, default=str), flush=True)


main()
