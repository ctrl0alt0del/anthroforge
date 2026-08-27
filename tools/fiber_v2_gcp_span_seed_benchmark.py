"""Refine one corrected span-SQP result with GCP, without production integration."""

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
import fiber_v2_gcp_roadmap_benchmark as gcp


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--accepted-cap", type=int, default=120)
    parser.add_argument("--force-ratio", type=float, default=.1)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _refine(request, snapshot, seed, config):
    direct, indices = gcp._direct_reference(request); rows, stats, histories, kappas = [], [], [], []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = gcp._span_request(request, seed, span, first, last, True)
        cap = gcp._span_cap(config.max_iterations, first, last, len(seed))
        result = gcp._span_solve(sub, snapshot, seed[first:last + 1], direct[first:last + 1],
                                 replace(config, max_iterations=cap))
        _append_span(rows, result[0]); stats.append(result[1]); histories.append(result[2]); kappas.append(result[3])
    return np.asarray(rows), stats, histories, kappas


def _append_span(rows, points):
    rows.extend(points if not rows else points[1:])


def _sample(request, snapshot, config):
    started = perf_counter(); package = gcp.solve_subfiber_sqp_fixed(request, snapshot=snapshot)
    seed_ms = _elapsed(started); seed = np.asarray(package.result.points, dtype=np.float64)
    if not package.result.validated: raise RuntimeError("corrected span-SQP seed is not validated")
    refined = perf_counter(); result = _refine(request, snapshot, seed, config); refine_ms = _elapsed(refined)
    validation = gcp.GcpStats(); valid = gcp._valid(request, snapshot, result[0], validation)
    return package, result, valid, seed_ms, refine_ms, _elapsed(started), validation.validation_ms


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)


def _timing(samples, index):
    values = [row[index] for row in samples]
    return {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values)}


def _free_geometry(points, pins):
    values = np.asarray(points); turns = gcp._turns(values); lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    free = np.asarray([index for index in range(1, len(values) - 1) if index not in pins], dtype=int)
    order = free[np.argsort(turns[free])[::-1]] if len(free) else free
    return {"path_length": float(lengths.sum()), "segment_cv": float(lengths.std() / max(lengths.mean(), 1e-12)),
            "worst_free_turn": float(turns[order[0]]) if len(order) else 0.0,
            "worst_free_node": int(order[0]) if len(order) else -1,
            "p95_free_turn": float(np.percentile(turns[free], 95)) if len(free) else 0.0,
            "top_free_turns": [(int(index), float(turns[index])) for index in order[:8]]}


def _movement(seed, result):
    distance = np.linalg.norm(np.asarray(result) - np.asarray(seed), axis=1)
    return {"maximum": float(distance.max()), "rms": float(np.sqrt(np.mean(distance ** 2)))}


def _payload(args, fiber, request, snapshot, capture, samples):
    package, result, valid = samples[-1][:3]; seed = np.asarray(package.result.points); points = result[0]
    _direct, pins = gcp._direct_reference(request); config = gcp.GcpConfig(args.force_ratio, args.accepted_cap)
    routes = (seed, points)
    return {"experiment": "span-SQP seed -> GCP", "file": bpy.data.filepath,
        "file_sha256": gcp.common._file_hash(bpy.data.filepath), "fiber": fiber.id,
        "capture_ms": capture, "node_count": len(seed), "pin_indices": tuple(map(int, pins)),
        "config": asdict(config), "seed_timing": _timing(samples, 3), "gcp_timing": _timing(samples, 4),
        "pipeline_timing": _timing(samples, 5), "seed_result": gcp.p3._result(package),
        "seed_geometry": _free_geometry(seed, set(pins)), "seed_points": seed.tolist(),
        "gcp_validated": valid, "gcp_geometry": _free_geometry(points, set(pins)),
        "gcp_points": points.tolist(), "gcp_stats": gcp._stats_sum(result[1]),
        "gcp_histories": result[2], "gcp_kappas": result[3], "movement_from_seed": _movement(seed, points),
        "final_validation_ms": samples[-1][6], "nearby_triangles": gcp.p3._nearby(snapshot, routes)}


def _capture(args):
    fiber, request, snapshot, _planner, capture = gcp._capture(args)
    config = gcp.GcpConfig(args.force_ratio, args.accepted_cap)
    samples = [_sample(request, snapshot, config) for _index in range(max(1, args.repeats))]
    return fiber, request, snapshot, capture, samples


def main():
    args = _args(); fiber, request, snapshot, capture, samples = _capture(args)
    record = _payload(args, fiber, request, snapshot, capture, samples)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: record[name] for name in ("seed_timing", "gcp_timing", "pipeline_timing")}
    summary.update(valid=record["gcp_validated"], seed=record["seed_geometry"], gcp=record["gcp_geometry"])
    print("AF_V2_GCP_SPAN_SEED", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
