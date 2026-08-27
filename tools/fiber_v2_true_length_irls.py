"""Real-Blender true-polyline-length IRLS experiment."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
import fiber_v2_roadmap_curvature_ablation as ablation
import fiber_v2_sqp_basin_test as basin
from anthroforge.core.vcp.v2.collision import cached_native_collision_world_batch
from anthroforge.core.vcp.v2.contact_core import V2ContactExperiment, _direct_reference, _planner_seed
from anthroforge.core.vcp.v2.planner import plan_reference_v43
from anthroforge.core.vcp.v2.production import clear_v2_production_caches
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


IRLS = V2ContactExperiment(true_length_irls=True)
VARIANTS = (("SQUARED_LENGTH_ZERO", None, 1.0), ("TRUE_LENGTH_IRLS", IRLS, 1.0),
            ("TRUE_LENGTH_IRLS_FIDELITY_01", IRLS, .1),
            ("TRUE_LENGTH_IRLS_FIDELITY_001", IRLS, .01))
SELECTED_VARIANTS = (VARIANTS[0], VARIANTS[-1])


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--accepted-cap", type=int, default=180); parser.add_argument("--subdivisions", type=int, default=4)
    parser.add_argument("--suite", choices=("all", "selected"), default="all")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)


def _solve_once(request, snapshot, experiment):
    clear_v2_production_caches(); started = perf_counter()
    package = solve_subfiber_sqp_fixed(request, snapshot=snapshot, use_planner=False,
        diagnostic_trace=False, experiment=experiment)
    return package, _elapsed(started)


def _samples(request, snapshot, experiment, repeats):
    rows = [_solve_once(request, snapshot, experiment) for _index in range(max(1, repeats))]
    deterministic = all(row[0].result.points == rows[0][0].result.points for row in rows[1:])
    return rows[-1][0], {"samples_ms": [row[1] for row in rows],
        "median_ms": median(row[1] for row in rows), "deterministic": deterministic}


def _variant(name, experiment, fidelity, request, snapshot, seed, pins, repeats):
    current = _fidelity_request(request, fidelity)
    package, timing = _samples(current, snapshot, experiment, repeats)
    points = np.asarray(package.result.points); lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return {"name": name, "objective": "TRUE_ARC_LENGTH" if experiment else "SQUARED_D1",
        "fidelity_weight": current.settings.fidelity_weight,
        "seed_points": seed.tolist(), "seed_geometry": basin._geometry(seed, set(pins)),
        "timing": timing, "result": p3._result(package), "result_points": points.tolist(),
        "result_geometry": basin._geometry(points, set(pins)), "arc_length": float(np.sum(lengths)),
        "result_energy_legacy": basin._energy(current, points),
        "result_validation": basin._validation(points, current, snapshot), "trace": asdict(package.trace)}


def _fidelity_request(request, scale):
    settings = replace(request.settings, fidelity_weight=request.settings.fidelity_weight * float(scale))
    return replace(request, settings=settings)


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    request = p3._override_cap(request, args.accepted_cap); world = cached_native_collision_world_batch(request.colliders)
    planner = plan_reference_v43(request, snapshot, native_world=world); direct, pins = _direct_reference(request)
    seed = _planner_seed(planner, pins, len(direct)); fixed, shortcut = ablation._shortcut_seed(
        request, planner, seed, pins, args.subdivisions)
    current = ablation._scaled_request(request, 0.0, fixed)
    variants = SELECTED_VARIANTS if args.suite == "selected" else VARIANTS
    rows = {name: _variant(name, experiment, fidelity, current, snapshot, fixed, pins, args.repeats)
            for name, experiment, fidelity in variants}
    return _payload(args, fiber, capture, planner, pins, shortcut, rows, snapshot)


def _payload(args, fiber, capture, planner, pins, shortcut, rows, snapshot):
    routes = [np.asarray(row[key]) for row in rows.values() for key in ("seed_points", "result_points")]
    return {"experiment": "true polyline length IRLS versus squared D1", "file": bpy.data.filepath,
        "file_sha256": common._file_hash(bpy.data.filepath), "fiber": fiber.id, "capture_ms": capture,
        "accepted_cap": args.accepted_cap, "subdivisions": args.subdivisions,
        "suite": args.suite, "pin_indices": pins,
        "planner": {"mode": planner.mode.value, "branches": [span.branch.value for span in planner.spans]},
        "shortcut": shortcut, "variants": rows, "nearby_triangles": p3._nearby(snapshot, routes)}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: _summary(row) for name, row in record["variants"].items()}
    print("AF_V2_TRUE_LENGTH_IRLS", json.dumps(summary), flush=True)


def _summary(row):
    return {"termination": row["result"]["termination"], "valid": row["result_validation"]["valid"],
        "length": row["arc_length"], "turn": row["result_geometry"]["worst_free_turn"],
        "accepted": row["result"]["diagnostics"]["accepted_steps"],
        "rejected": row["result"]["diagnostics"]["rejected_steps"], "ms": row["timing"]["median_ms"]}


if __name__ == "__main__":
    main()
