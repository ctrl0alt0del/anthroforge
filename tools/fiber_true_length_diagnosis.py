"""Profile V1 and true-length span-SQP on one real Blender Fiber."""

import argparse
import cProfile
from dataclasses import asdict, replace
import json
from pathlib import Path
import pstats
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
import fiber_v2_roadmap_curvature_ablation as ablation
import fiber_v2_sqp_basin_test as basin
from anthroforge.core.vcp import runtime_state
from anthroforge.core.vcp.fiber_progressive import begin_fiber_solve
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.v2.collision import cached_native_collision_world_batch
from anthroforge.core.vcp.v2 import collision_native
from anthroforge.core.vcp.v2.contact_core import V2ContactExperiment, _direct_reference, _planner_seed
from anthroforge.core.vcp.v2.planner import plan_reference_v43
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--accepted-cap", type=int, default=180)
    parser.add_argument("--v1-repeats", type=int, default=3); parser.add_argument("--profile-limit", type=int, default=60)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _timed(call):
    started = perf_counter(); value = call()
    return value, 1000.0 * (perf_counter() - started)


def _profiled(call, limit):
    profiler = cProfile.Profile(); profiler.enable(); value, elapsed = _timed(call); profiler.disable()
    return value, elapsed, _profile_rows(profiler, limit)


def _profile_rows(profiler, limit):
    rows = []
    for (file, line, name), values in pstats.Stats(profiler).stats.items():
        rows.append({"file": file, "line": line, "name": name, "calls": values[1],
            "self_ms": 1000.0 * values[2], "cumulative_ms": 1000.0 * values[3]})
    return sorted(rows, key=lambda row: row["cumulative_ms"], reverse=True)[:int(limit)]


def _v1(root, fiber, depsgraph, repeats, snapshot, request, pins):
    solve = lambda: _v1_once(root, fiber, depsgraph)
    samples = [_timed(solve) for _index in range(repeats)]
    points, profiled_ms, profile = _profiled(solve, 60)
    values = np.asarray(points, dtype=np.float64)
    return {"samples_ms": [row[1] for row in samples], "median_ms": median(row[1] for row in samples),
        "profiled_ms": profiled_ms, "profile": profile, "points": values.tolist(),
        "geometry": basin._geometry(values, set(pins)), "validation": basin._validation(values, request, snapshot),
        "runtime": _v1_runtime(fiber)}


def _v1_once(root, fiber, depsgraph):
    preview = bool(getattr(fiber, "preview_planner_route", False))
    try:
        fiber.preview_planner_route = False; solver = FiberSolver(); solver.clear_cache(fiber.id)
        session = begin_fiber_solve(solver, root, fiber, bpy.context.scene, depsgraph,
                                    quality="INTERACTIVE", explicit_engine="V1")
        while not session.done: session.step(1.0e9)
        return session.result().points
    finally:
        fiber.preview_planner_route = preview


def _v1_runtime(fiber):
    return {"status": runtime_state.fiber_recompute_status(fiber),
        "planner_ms": runtime_state.fiber_planner_ms(fiber), "refine_ms": runtime_state.fiber_refine_ms(fiber),
        "route": runtime_state.fiber_route_mode(fiber), "active_colliders": runtime_state.fiber_active_colliders(fiber),
        "eps_disp": runtime_state.fiber_eps_disp(fiber), "eps_pen": runtime_state.fiber_eps_pen(fiber)}


def _prepared(root, fiber, depsgraph, cap):
    request, snapshot, capture = p3._capture(root, fiber, depsgraph)
    request = p3._override_cap(request, cap); world = cached_native_collision_world_batch(request.colliders)
    planner, planner_ms = _timed(lambda: plan_reference_v43(request, snapshot, native_world=world))
    direct, pins = _direct_reference(request); seed = _planner_seed(planner, pins, len(direct))
    fixed, shortcut_ms = _timed(lambda: ablation._shortcut_seed(request, planner, seed, pins, 4))
    settings = replace(request.settings, curvature_weight=0.0, fidelity_weight=.01 * request.settings.fidelity_weight)
    current = replace(request, settings=settings, warm_seed=tuple(map(tuple, fixed[0])))
    return current, snapshot, pins, {"capture_ms": capture, "planner_ms": planner_ms,
        "shortcut_ms": shortcut_ms, "shortcut": fixed[1]}


def _irls(request, snapshot, pins, limit):
    experiment = V2ContactExperiment(true_length_irls=True)
    solve = lambda: solve_subfiber_sqp_fixed(request, snapshot, False, False, experiment)
    package, elapsed, profile = _profiled(solve, limit); points = np.asarray(package.result.points)
    _cache_default_native_library(); cached, cached_ms, cached_profile = _profiled(solve, limit)
    return {"profiled_ms": elapsed, "cached_native_ms": cached_ms,
        "cached_native_equal": cached.result.points == package.result.points,
        "profile": profile, "cached_native_profile": cached_profile, "result": p3._result(package),
        "trace": asdict(package.trace), "points": points.tolist(),
        "geometry": basin._geometry(points, set(pins)), "validation": basin._validation(points, request, snapshot)}


def _cache_default_native_library():
    original = collision_native.load_native; library = original()
    collision_native.load_native = lambda path=None: library if path is None else original(path)


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); request, snapshot, pins, preparation = _prepared(
        root, fiber, depsgraph, args.accepted_cap)
    v1 = _v1(root, fiber, depsgraph, args.v1_repeats, snapshot, request, pins)
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
        "fiber": fiber.id, "accepted_cap": args.accepted_cap, "preparation": preparation,
        "v1": v1, "irls": _irls(request, snapshot, pins, args.profile_limit)}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_TRUE_LENGTH_DIAG", json.dumps(_summary(record)), flush=True)


def _summary(record):
    irls = record["irls"]; v1 = record["v1"]
    return {"fiber": record["fiber"], "v1_ms": v1["median_ms"], "v1_valid": v1["validation"]["valid"],
        "irls_profiled_ms": irls["profiled_ms"], "irls_valid": irls["validation"]["valid"],
        "irls_termination": irls["result"]["termination"]}


if __name__ == "__main__":
    main()
