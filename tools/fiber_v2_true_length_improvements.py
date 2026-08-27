"""Real-Blender ablation for true-length SQP performance and quality fixes."""

import json
from dataclasses import asdict, replace
from pathlib import Path
import sys

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_roadmap_curvature_ablation as ablation
import fiber_v2_sqp_basin_test as basin
import fiber_v2_true_length_irls as base
from anthroforge.core.vcp.v2.collision import cached_native_collision_world_batch
from anthroforge.core.vcp.v2.contact_core import V2ContactExperiment, _direct_reference, _planner_seed
from anthroforge.core.vcp.v2.planner import plan_reference_v43
from anthroforge.tools import fiber_v2_planner_benchmark as common


IRLS = dict(true_length_irls=True)
VARIANTS = (
    ("BASE_IRLS", V2ContactExperiment(**IRLS), 0.0),
    ("STABLE_LIMITERS", V2ContactExperiment(**IRLS, stable_limiters=True), 0.0),
    ("MANIFOLD", V2ContactExperiment(**IRLS, contact_manifold_reduction=True), 0.0),
    ("SPACING_005", V2ContactExperiment(**IRLS, spacing_weight_ratio=.05), 0.0),
    ("SPACING_01", V2ContactExperiment(**IRLS, spacing_weight_ratio=.1), 0.0),
    ("SPACING_025", V2ContactExperiment(**IRLS, spacing_weight_ratio=.25), 0.0),
    ("SPACING_05", V2ContactExperiment(**IRLS, spacing_weight_ratio=.5), 0.0),
    ("ALL_01", V2ContactExperiment(**IRLS, stable_limiters=True,
                                    contact_manifold_reduction=True, spacing_weight_ratio=.1), 0.0),
    ("ALL_025", V2ContactExperiment(**IRLS, stable_limiters=True,
                                     contact_manifold_reduction=True, spacing_weight_ratio=.25), 0.0),
    ("CURV_001", V2ContactExperiment(**IRLS), .001),
    ("CURV_01", V2ContactExperiment(**IRLS), .01),
    ("CURV_0001_SPACE_05", V2ContactExperiment(**IRLS, spacing_weight_ratio=.5), .0001),
    ("CURV_001_SPACE_05", V2ContactExperiment(**IRLS, spacing_weight_ratio=.5), .001),
    ("CURV_01_SPACE_05", V2ContactExperiment(**IRLS, spacing_weight_ratio=.5), .01),
    ("ADAPTIVE", V2ContactExperiment(**IRLS, adaptive_quality=True), None),
)
SELECTED_VARIANTS = (VARIANTS[0], VARIANTS[-1])


def _variant(name, experiment, request, snapshot, seed, pins, repeats):
    package, timing = base._samples(request, snapshot, experiment, repeats)
    points = np.asarray(package.result.points); lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return {"name": name, "experiment": asdict(experiment), "timing": timing,
        "result": base.p3._result(package), "result_points": points.tolist(),
        "geometry": basin._geometry(points, set(pins)), "arc_length": float(np.sum(lengths)),
        "segment_cv": _segment_cv(lengths), "validation": basin._validation(points, request, snapshot),
        "trace": asdict(package.trace), "seed_points": seed.tolist()}


def _segment_cv(lengths):
    return float(np.std(lengths) / np.mean(lengths)) if len(lengths) and np.mean(lengths) else 0.0


def _prepared(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = base.p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    request = base.p3._override_cap(request, args.accepted_cap)
    world = cached_native_collision_world_batch(request.colliders)
    planner = plan_reference_v43(request, snapshot, native_world=world)
    direct, pins = _direct_reference(request); seed = _planner_seed(planner, pins, len(direct))
    fixed, shortcut = ablation._shortcut_seed(request, planner, seed, pins, args.subdivisions)
    return fiber, request, snapshot, capture, planner, pins, fixed, shortcut


def _variant_request(request, seed, curvature):
    current = request if curvature is None else ablation._scaled_request(request, curvature, seed)
    if curvature is None: current = replace(current, warm_seed=tuple(map(tuple, seed)))
    return base._fidelity_request(current, .01)


def _record(args):
    fiber, request, snapshot, capture, planner, pins, seed, shortcut = _prepared(args)
    variants = VARIANTS if args.suite == "all" else SELECTED_VARIANTS
    rows = {name: _variant(name, experiment, _variant_request(request, seed, curvature),
            snapshot, seed, pins, args.repeats) for name, experiment, curvature in variants}
    routes = [np.asarray(row["result_points"]) for row in rows.values()]
    return {"experiment": "true-length SQP fixes", "file": bpy.data.filepath,
        "file_sha256": common._file_hash(bpy.data.filepath), "fiber": fiber.id,
        "capture_ms": capture, "accepted_cap": args.accepted_cap, "pin_indices": pins,
        "planner": {"mode": planner.mode.value, "branches": [row.branch.value for row in planner.spans]},
        "shortcut": shortcut, "variants": rows, "nearby_triangles": base.p3._nearby(snapshot, routes)}


def _summary(row):
    diagnostics = row["result"]["diagnostics"]
    return {"termination": row["result"]["termination"], "valid": row["validation"]["valid"],
        "length": row["arc_length"], "turn": row["geometry"]["worst_free_turn"],
        "segment_cv": row["segment_cv"], "accepted": diagnostics["accepted_steps"],
        "rejected": diagnostics["rejected_steps"], "condition": diagnostics["block_factor_condition"],
        "ms": row["timing"]["median_ms"]}


def main():
    args = base._args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_TRUE_LENGTH_FIXES", json.dumps({key: _summary(row)
          for key, row in record["variants"].items()}), flush=True)


if __name__ == "__main__":
    main()
