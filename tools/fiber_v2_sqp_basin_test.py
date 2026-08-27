"""Multi-start test of the exact corrected span-SQP objective."""

import argparse
from dataclasses import asdict, replace
import itertools
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
from anthroforge.core.vcp.v2.collision import cached_native_collision_world_batch
from anthroforge.core.vcp.v2.contact_core import _direct_reference, _planner_seed, _resample
from anthroforge.core.vcp.v2.planner import plan_reference_v43
from anthroforge.core.vcp.v2.production import clear_v2_production_caches
from anthroforge.core.vcp.v2.structural import _static_settings, static_fiber_energy
from anthroforge.core.vcp.v2.subfiber_sqp import _span_request, solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


SEED_ORDER = ("DIRECT", "PLANNER", "STORED_PROXY", "V1", "V2_BASE", "WHOLE_SQP")


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--accepted-cap", type=int, default=180)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)


def _timed(call):
    started = perf_counter(); value = call()
    return value, _elapsed(started)


def _pin_indices(points, anchors):
    values = np.asarray(points); rows, start = [0], 1
    for index, anchor in enumerate(anchors[1:-1], start=1):
        stop = len(values) - (len(anchors) - index - 1)
        local = np.linalg.norm(values[start:stop] - np.asarray(anchor.point), axis=1)
        chosen = start + int(np.argmin(local)); rows.append(chosen); start = chosen + 1
    return tuple(rows + [len(values) - 1])


def _align(points, request, target_pins):
    values = np.asarray(points, dtype=np.float64); source_pins = _pin_indices(values, request.anchors)
    rows = []
    for span, (first, last) in enumerate(zip(target_pins[:-1], target_pins[1:])):
        part = _resample(values[source_pins[span]:source_pins[span + 1] + 1], last - first + 1)
        rows.extend(part if not rows else part[1:])
    output = np.asarray(rows); error = _pin_error(values, source_pins, request.anchors)
    for index, anchor in zip(target_pins, request.anchors): output[index] = anchor.point
    return np.ascontiguousarray(output), source_pins, error


def _pin_error(points, indices, anchors):
    rows = (np.linalg.norm(points[index] - np.asarray(anchor.point))
            for index, anchor in zip(indices, anchors))
    return float(max(rows, default=0.0))


def _planner_source(request, snapshot, direct, pins):
    world = cached_native_collision_world_batch(request.colliders)
    planner, elapsed = _timed(lambda: plan_reference_v43(request, snapshot, native_world=world))
    if not planner.succeeded: return None, {"termination": planner.termination.value, "ms": elapsed}
    seed = _planner_seed(planner, pins, len(direct))
    return seed, {"termination": planner.termination.value, "mode": planner.mode.value,
                  "branches": [row.branch.value for row in planner.spans], "ms": elapsed}


def _package_source(request, snapshot, controller):
    clear_v2_production_caches(); package, elapsed = _timed(lambda: p3._solve(request, snapshot, controller))
    info = p3._result(package); info["ms"] = elapsed
    points = np.asarray(package.result.points, dtype=np.float64)
    return (points if len(points) else None), info


def _raw_sources(root, fiber, request, snapshot, depsgraph):
    direct, pins = _direct_reference(request); rows = {"DIRECT": (direct, {"ms": 0.0})}
    rows["PLANNER"] = _planner_source(request, snapshot, direct, pins)
    proxy = common._proxy(root, fiber.id); stored = common._curve_points(proxy) if proxy else None
    rows["STORED_PROXY"] = (stored, {"ms": 0.0})
    v1, v1_ms = _timed(lambda: p3._v1(root, fiber, depsgraph)); rows["V1"] = (np.asarray(v1["points"]), {"ms": v1_ms})
    rows["V2_BASE"] = _package_source(request, snapshot, "BASE")
    rows["WHOLE_SQP"] = _package_source(request, snapshot, "SQP")
    return rows, pins


def _owner_span(points, pins, request):
    lengths = []
    for pin in pins:
        if pin: lengths.append(np.linalg.norm(points[pin] - points[pin - 1]))
        if pin + 1 < len(points): lengths.append(np.linalg.norm(points[pin + 1] - points[pin]))
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    return max(4.0 * slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)


def _span_validation(world, points, owners, span, threshold):
    edges = tuple((index, index + 1) for index in range(len(points) - 1))
    edge_owners = tuple((owners[0] if index == 0 else "",
                         owners[1] if index + 2 == len(points) else "") for index in range(len(edges)))
    result = world.validate(points, edges, edge_owners, span, threshold)
    bad = tuple(index for index, clear in enumerate(result.clear) if not clear)
    return bool(all(result.clear)), max(0.0, threshold - result.minimum), bad


def _validation(points, request, _snapshot):
    _direct, indices = _direct_reference(request); world = cached_native_collision_world_batch(request.colliders)
    span = _owner_span(points, indices, request); threshold = max(0.0,
        request.collision_policy.collision_radius - request.tolerances.clearance_slack)
    rows = []
    for index, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        owners = request.anchors[index].owner_id, request.anchors[index + 1].owner_id
        rows.append(_span_validation(world, points[first:last + 1], owners, span, threshold))
    return {"valid": all(row[0] for row in rows), "node_residual": 0.0,
        "edge_residual": max((row[1] for row in rows), default=0.0),
        "violating_nodes": [], "violating_edges": [list(row[2]) for row in rows], "contained_nodes": []}


def _energy(request, points):
    _direct, indices = _direct_reference(request); totals = np.zeros(3)
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        sub = _span_request(request, points, span, first, last, True)
        reference, _pins = _direct_reference(sub); settings = _static_settings(sub.settings)
        value = static_fiber_energy(points[first:last + 1], reference, settings)
        totals += value.fidelity, value.length, value.bend
    return {"fidelity": float(totals[0]), "length": float(totals[1]),
            "curvature": float(totals[2]), "total": float(totals.sum())}


def _turns(points):
    first, second = points[1:-1] - points[:-2], points[2:] - points[1:-1]
    scale = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1)
    cosine = np.sum(first * second, axis=1) / np.maximum(scale, 1.0e-15)
    return np.r_[0.0, np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))), 0.0]


def _geometry(points, pins):
    edges = np.linalg.norm(np.diff(points, axis=0), axis=1); turns = _turns(points)
    free = [index for index in range(1, len(points) - 1) if index not in pins]
    worst = max(free, key=lambda index: turns[index]) if free else -1
    return {"path_length": float(edges.sum()), "segment_cv": float(edges.std() / max(edges.mean(), 1e-15)),
            "worst_free_turn": float(turns[worst]) if worst >= 0 else 0.0,
            "worst_free_node": worst, "p95_free_turn": float(np.percentile(turns[free], 95)) if free else 0.0}


def _relax_once(request, snapshot, seed):
    warm = tuple(map(tuple, np.asarray(seed, dtype=np.float64)))
    return solve_subfiber_sqp_fixed(replace(request, warm_seed=warm), snapshot=snapshot, use_planner=False)


def _relax(request, snapshot, seed, repeats):
    samples = []
    for _index in range(max(1, repeats)):
        clear_v2_production_caches(); samples.append(_timed(lambda: _relax_once(request, snapshot, seed)))
    points = np.asarray(samples[-1][0].result.points, dtype=np.float64)
    deterministic = all(row[0].result.points == samples[0][0].result.points for row in samples[1:])
    return samples[-1][0], points, {"samples_ms": [row[1] for row in samples],
        "median_ms": median(row[1] for row in samples), "deterministic": deterministic}


def _case(name, raw, info, request, snapshot, pins, repeats):
    if raw is None or len(raw) < len(request.anchors): return {"available": False, "source": info}
    seed, source_pins, pin_error = _align(raw, request, pins)
    base = {"available": True, "source": info, "source_pin_indices": source_pins,
        "source_pin_error": pin_error, "seed_validation": _validation(seed, request, snapshot),
        "seed_energy": _energy(request, seed), "seed_geometry": _geometry(seed, set(pins)),
        "seed_points": seed.tolist()}
    try: package, result, timing = _relax(request, snapshot, seed, repeats)
    except Exception as error: return base | {"relaxation_error": f"{type(error).__name__}: {error}"}
    return base | {"timing": timing, "result": p3._result(package),
        "result_validation": _validation(result, request, snapshot),
        "result_energy": _energy(request, result), "result_geometry": _geometry(result, set(pins)),
        "result_points": result.tolist(), "trace": asdict(package.trace)}


def _pair(first, second, cases, threshold):
    a, b = np.asarray(cases[first]["result_points"]), np.asarray(cases[second]["result_points"])
    distances = np.linalg.norm(a - b, axis=1); delta = cases[second]["result_energy"]["total"] - cases[first]["result_energy"]["total"]
    return {"first": first, "second": second, "maximum_distance": float(distances.max()),
        "rms_distance": float(np.sqrt(np.mean(distances ** 2))), "energy_second_minus_first": delta,
        "same_basin": bool(float(distances.max()) <= threshold)}


def _comparison(cases, request):
    usable = [name for name in SEED_ORDER if cases.get(name, {}).get("result", {}).get("validated")
              and cases[name].get("result_validation", {}).get("valid")]
    threshold = max(5.0 * request.tolerances.clearance_slack, 1.0e-6 * request.tolerances.length_scale)
    pairs = [_pair(first, second, cases, threshold) for first, second in itertools.combinations(usable, 2)]
    baseline = cases.get("PLANNER", {}).get("result_energy", {}).get("total", float("inf"))
    converged = [name for name in usable if cases[name]["result"]["termination"] == "CONVERGED"]
    best = min(converged, key=lambda name: cases[name]["result_energy"]["total"]) if converged else ""
    minima_pairs = [row for row in pairs if row["first"] in converged and row["second"] in converged]
    distinct = any(not row["same_basin"] for row in minima_pairs)
    better = bool(best and cases[best]["result_energy"]["total"] < baseline - 1.0e-8)
    verdict = "LOWER_CONVERGED_BASIN_CONFIRMED" if distinct and better else "NO_ALTERNATIVE_CONVERGED_BASIN_FOUND"
    return {"threshold": threshold, "usable": usable, "converged": converged, "best_converged": best,
            "planner_energy": baseline, "distinct_converged": distinct,
            "lower_converged_than_planner": better, "verdict": verdict, "pairs": pairs}


def _nearby(snapshot, cases):
    rows = [np.asarray(row["result_points"]) for row in cases.values() if "result_points" in row]
    return p3._nearby(snapshot, rows)


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    request, snapshot, capture = p3._capture(root, fiber, depsgraph); request = p3._override_cap(request, args.accepted_cap)
    sources, pins = _raw_sources(root, fiber, request, snapshot, depsgraph)
    cases = {name: _case(name, *sources[name], request, snapshot, pins, args.repeats) for name in SEED_ORDER}
    return {"experiment": "exact corrected span-SQP multistart basin test", "file": bpy.data.filepath,
        "file_sha256": common._file_hash(bpy.data.filepath), "fiber": fiber.id, "capture_ms": capture,
        "accepted_cap": args.accepted_cap, "pin_indices": pins, "cases": cases,
        "comparison": _comparison(cases, request), "nearby_triangles": _nearby(snapshot, cases)}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: {"valid": row.get("result_validation", {}).get("valid"),
        "energy": row.get("result_energy", {}).get("total"), "ms": row.get("timing", {}).get("median_ms")}
        for name, row in record["cases"].items()}
    print("AF_V2_SQP_BASIN", json.dumps({"verdict": record["comparison"]["verdict"], "cases": summary}), flush=True)


if __name__ == "__main__":
    main()
