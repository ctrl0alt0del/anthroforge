"""Read-only benchmark for the isolated V3 transverse-corridor experiment."""

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
from anthroforge.core.vcp.v3_experiment import clear_v3_experiment_caches, solve_v3_corridor
from anthroforge.core.vcp.v3_transverse_experiment import solve_v3_transverse
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=5)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _timed(call):
    started = perf_counter(); value = call(); return value, 1000.0 * (perf_counter() - started)


def _turns(points, pins):
    values = np.asarray(points); first, second = np.diff(values, axis=0)[:-1], np.diff(values, axis=0)[1:]
    scale = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1)
    angles = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", first, second) / np.maximum(scale, 1e-12), -1, 1)))
    free = np.asarray([value for index, value in enumerate(angles, 1) if index not in set(pins)])
    return {"max": float(np.max(angles)), "p95": float(np.percentile(angles, 95)),
            "free_max": float(np.max(free)), "free_p95": float(np.percentile(free, 95))}


def _path(points, pins):
    values = np.asarray(points)
    return {"points": values.tolist(), "length": float(np.linalg.norm(np.diff(values, axis=0), axis=1).sum()),
            "turns": _turns(values, pins)}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders = common._colliders(bpy.context.scene, root, depsgraph)
    snapshot = common.build_triangle_snapshot(colliders); anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
    request = common._request(root, fiber, anchors, colliders)
    settings = replace(request.settings, max_accepted_steps=args.steps)
    return fiber, snapshot, replace(request, settings=settings)


def _transverse_payload(result, timings):
    pins = result.first_pass.corridor.pin_indices
    return {"timing_ms": timings, "median_ms": statistics.median(timings), "valid": result.valid,
            "accepted": result.accepted, "termination": result.termination, "message": result.message,
            "path": _path(result.points, pins), "candidate": _path(result.candidate_points, pins),
            "lower": _path(result.lower, pins), "middle": _path(result.middle, pins),
            "upper": _path(result.upper, pins), "beta": result.beta, "trace": vars(result.trace)}


def _v3_payload(result, timing):
    pins = result.corridor.pin_indices
    return {"timing_ms": timing, "valid": result.valid, "termination": result.termination,
            "path": _path(result.points, pins), "trace": vars(result.trace)}


def _v2_payload(package, timing, pins):
    result = package.result
    return {"timing_ms": timing, "valid": result.validated, "termination": result.termination.value,
            "path": _path(result.points, pins), "trace": vars(package.trace)}


def _mode_rows(args, request, snapshot, first, mode):
    rows = [_timed(lambda: solve_v3_transverse(request, snapshot, first, mode)) for _ in range(args.repeats)]
    return rows[-1][0], [row[1] for row in rows]


def _record(args):
    fiber, snapshot, request = _capture(args); clear_v3_experiment_caches()
    first, first_ms = _timed(lambda: solve_v3_corridor(request, snapshot))
    full, full_ms = _mode_rows(args, request, snapshot, first, "full")
    window, window_ms = _mode_rows(args, request, snapshot, first, "windowed")
    v2, v2_ms = _timed(lambda: solve_v2(request, snapshot)); pins = first.corridor.pin_indices
    return {"file": bpy.data.filepath, "sha256": common._file_hash(bpy.data.filepath), "fiber": fiber.id,
            "steps": args.steps, "pin_indices": pins, "v2": _v2_payload(v2, v2_ms, pins),
            "v3_first": _v3_payload(first, first_ms), "transverse_full": _transverse_payload(full, full_ms),
            "transverse_window": _transverse_payload(window, window_ms),
            "nearby_triangles": _nearby(snapshot, first, full, window)}


def _nearby(snapshot, first, full, window):
    routes = np.vstack((first.points, full.lower, full.upper, window.lower, window.upper))
    padding = max(0.05, 0.15 * float(np.linalg.norm(np.ptp(routes, axis=0))))
    low, high = routes.min(axis=0) - padding, routes.max(axis=0) + padding
    faces = snapshot.vertices[snapshot.triangles]
    selected = np.all(faces.max(axis=1) >= low, axis=1) & np.all(faces.min(axis=1) <= high, axis=1)
    return faces[selected].tolist()


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {key: value for key, value in record.items() if key != "nearby_triangles"}
    for value in summary.values():
        if isinstance(value, dict):
            for key in ("path", "candidate", "lower", "middle", "upper"): value.get(key, {}).pop("points", None)
    print("AF_V3_TRANSVERSE " + json.dumps(summary, default=str), flush=True)


main()
