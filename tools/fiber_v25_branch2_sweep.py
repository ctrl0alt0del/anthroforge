"""Sweep V2.4 solver weights on one fixed lifted-bridge production route."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot_known,
    cached_native_collision_world_batch, solve_v24, v22_snapshot_key)
from anthroforge.core.vcp.v2 import solver as solver_impl
from anthroforge.core.vcp.v2 import solver_v23 as v23
from anthroforge.tools import fiber_v24_benchmark as v24
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--fiber-id", default="FIBER_2")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"):
        return
    import anthroforge
    anthroforge.register()


def _capture(root, fiber, depsgraph):
    colliders, _elapsed = v24._native_colliders(bpy.context.scene, root, depsgraph)
    anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
    request = common._request(root, fiber, anchors, colliders)
    world = cached_native_collision_world_batch(colliders, v22_snapshot_key(request))
    snapshot = build_triangle_snapshot_known(colliders, world.closed_flags)
    return request, snapshot, anchors


def _configs():
    for proximal in (0.01, 0.02, 0.05, 0.10):
        for length in (0.45, 0.90, 1.80):
            for curvature in (0.02, 0.05, 0.10, 0.20):
                yield proximal, length, curvature


def _turns(points):
    edges = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    if len(edges) < 2:
        return np.zeros(0, dtype=np.float64)
    unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    return np.degrees(np.arccos(np.clip(np.sum(unit[:-1] * unit[1:], axis=1), -1.0, 1.0)))


def _metrics(points):
    values = np.asarray(points, dtype=np.float64); turns = _turns(values)
    lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    return {"length": float(np.sum(lengths)), "max_turn_deg": _max(turns),
            "p95_turn_deg": _percentile(turns, 95), "total_turn_deg": float(np.sum(turns))}


def _max(values):
    return float(np.max(values)) if len(values) else 0.0


def _percentile(values, value):
    return float(np.percentile(values, value)) if len(values) else 0.0


def _request_with(request, config):
    proximal, length, curvature = config
    settings = replace(request.settings, length_weight=length, curvature_weight=curvature)
    return replace(request, settings=settings), proximal


def _measure(request, snapshot, config, repeats=3):
    configured, proximal = _request_with(request, config); solver_impl.PROXIMAL_WEIGHT = proximal
    samples, package = [], None
    for _index in range(repeats):
        started = perf_counter(); package = solve_v24(configured, snapshot)
        samples.append(1000.0 * (perf_counter() - started))
    return _row(config, samples, package)


def _row(config, samples, package):
    result = package.result; metrics = _metrics(result.points)
    return {"proximal": config[0], "length_weight": config[1],
            "curvature_weight": config[2], "median_ms": median(samples),
            "termination": result.termination.value, "validated": result.validated,
            "metrics": metrics, "trace": vars(package.trace), "points": result.points}


def _rank(row):
    invalid = 0 if row["validated"] else 1; metrics = row["metrics"]
    return invalid, metrics["max_turn_deg"], metrics["p95_turn_deg"], row["median_ms"]


def _sweep(request, snapshot, planner):
    original_planner, original_weight = v23._planner, solver_impl.PROXIMAL_WEIGHT
    v23._planner = lambda *_args, **_kwargs: (planner, (True, True, 0.0, 0), (True, False, False))
    try:
        return sorted((_measure(request, snapshot, row) for row in _configs()), key=_rank)
    finally:
        v23._planner, solver_impl.PROXIMAL_WEIGHT = original_planner, original_weight


def _source(root, fiber):
    proxy = common._proxy(root, fiber.id)
    return common._curve_points(proxy).tolist() if proxy else []


def _visual(root, fiber, planner, baseline, best, snapshot):
    paths = tuple(np.asarray(row) for row in (_source(root, fiber), planner.reference,
                                              baseline.result.points, best["points"]))
    triangles = p41._nearby_faces(snapshot, paths)
    return {"source": paths[0].tolist(), "planner": paths[1].tolist(),
            "v24": paths[2].tolist(), "v25": paths[3].tolist(),
            "nearby_triangles": triangles.tolist()}


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, anchors = _capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    baseline = solve_v24(request, snapshot); rows = _sweep(request, snapshot, baseline.planner)
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
            "fiber": fiber.id, "anchors": [list(row.point) for row in anchors],
            "planner_metrics": _metrics(baseline.planner.reference), "baseline": _baseline(baseline),
            "best": rows[0], "top": rows[:8], "rows": rows,
            "visual": _visual(root, fiber, baseline.planner, baseline, rows[0], snapshot)}


def _baseline(package):
    return {"termination": package.result.termination.value, "validated": package.result.validated,
            "metrics": _metrics(package.result.points), "trace": vars(package.trace),
            "points": package.result.points}


def main():
    _ensure_addon(); args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V25_BRANCH2_SWEEP " + json.dumps({"fiber": record["fiber"],
          "planner": record["planner_metrics"], "best": record["best"]}, default=str), flush=True)


if __name__ == "__main__":
    main()
