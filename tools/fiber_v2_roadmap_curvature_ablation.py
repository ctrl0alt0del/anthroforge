"""Real-Blender ROADMAP shortcut and curvature-weight ablation."""

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
import fiber_v2_sqp_basin_test as basin
from anthroforge.core.vcp.v2.collision import cached_native_collision_world_batch
from anthroforge.core.vcp.v2.contact_core import _direct_reference, _planner_seed
from anthroforge.core.vcp.v2.planner import plan_reference_v43
from anthroforge.core.vcp.v2.production import clear_v2_production_caches
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


VARIANTS = (("BASELINE", False, 1.0), ("SHORTCUT", True, 1.0),
            ("CURVATURE_HALF", True, .5), ("CURVATURE_THIRD", True, 1.0 / 3.0),
            ("UNSHORTCUT_CURVATURE_ZERO", False, 0.0), ("CURVATURE_ZERO", True, 0.0))
BROAD_VARIANTS = (VARIANTS[0], VARIANTS[-2], VARIANTS[-1])
SHORTCUT_ZERO_VARIANTS = (VARIANTS[-1],)


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--accepted-cap", type=int, default=180); parser.add_argument("--subdivisions", type=int, default=4)
    parser.add_argument("--suite", choices=("full", "broad", "shortcut-zero"), default="full")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)


def _chord(first, second, edge_count):
    steps = np.linspace(0.0, 1.0, edge_count + 1)[:, None]
    return first + steps * (second - first)


def _chord_clear(world, points, owners, span, threshold, stats):
    edges = tuple((index, index + 1) for index in range(len(points) - 1))
    edge_owners = tuple((owners[0] if index == 0 else "",
        owners[1] if index + 1 == len(edges) else "") for index in range(len(edges)))
    result = world.validate(points, edges, edge_owners, span, threshold)
    stats["attempts"] += 1; stats["candidate_pairs"] += result.candidate_pairs
    stats["tested_pairs"] += result.tested_pairs
    return bool(all(result.clear))


def _shortcut_walk(points, owners, world, span, threshold, stats):
    output, controls, index = np.array(points, copy=True), 1, 0
    while index < len(points) - 1:
        for candidate in range(len(points) - 1, index, -1):
            chord = _chord(output[index], points[candidate], candidate - index)
            local = (owners[0] if index == 0 else "",
                     owners[1] if candidate + 1 == len(points) else "")
            if _chord_clear(world, chord, local, span, threshold, stats): break
        stats["accepted"] += int(candidate > index + 1); controls += 1
        output[index:candidate + 1] = chord; index = candidate
    return output, controls


def _span_shortcut(points, owners, budget, context):
    fixed, controls = _shortcut_walk(points, owners, *context[:4])
    context[3]["route_nodes_before"] += len(points); context[3]["route_nodes_after"] += controls
    return fixed


def _shortcut_seed(request, planner, seed, pins, subdivisions):
    world = cached_native_collision_world_batch(request.colliders); span = basin._owner_span(seed, pins, request)
    threshold = max(0.0, request.collision_policy.collision_radius - request.tolerances.clearance_slack)
    stats = {"attempts": 0, "accepted": 0, "candidate_pairs": 0, "tested_pairs": 0,
             "route_nodes_before": 0, "route_nodes_after": 0, "fallbacks": 0}
    context, rows = (world, span, threshold, stats, max(1, subdivisions)), []
    for index, (first, last) in enumerate(zip(pins[:-1], pins[1:])):
        block = seed[first:last + 1]; owners = request.anchors[index].owner_id, request.anchors[index + 1].owner_id
        fixed = _span_shortcut(block, owners, last - first, context) if planner.spans[index].branch.value == "ROADMAP" else block
        rows.extend(fixed if not rows else fixed[1:])
    return np.asarray(rows), stats


def _scaled_request(request, scale, seed):
    settings = replace(request.settings, curvature_weight=request.settings.curvature_weight * scale)
    return replace(request, settings=settings, warm_seed=tuple(map(tuple, seed)))


def _solve_once(request, snapshot):
    clear_v2_production_caches(); started = perf_counter()
    package = solve_subfiber_sqp_fixed(request, snapshot=snapshot, use_planner=False)
    return package, _elapsed(started)


def _samples(request, snapshot, repeats):
    rows = [_solve_once(request, snapshot) for _index in range(max(1, repeats))]
    deterministic = all(row[0].result.points == rows[0][0].result.points for row in rows[1:])
    return rows[-1][0], {"samples_ms": [row[1] for row in rows],
        "median_ms": median(row[1] for row in rows), "deterministic": deterministic}


def _raw_curvature(points):
    values = np.asarray(points); second = np.diff(values, n=2, axis=0)
    return float(np.sum(second * second))


def _variant(name, shortcut, scale, request, snapshot, seeds, pins, repeats):
    seed = seeds[1] if shortcut else seeds[0]; current = _scaled_request(request, scale, seed)
    package, timing = _samples(current, snapshot, repeats); points = np.asarray(package.result.points)
    return {"name": name, "shortcut": shortcut, "curvature_scale": scale,
        "curvature_weight": current.settings.curvature_weight, "seed_points": seed.tolist(),
        "seed_geometry": basin._geometry(seed, set(pins)), "seed_raw_curvature": _raw_curvature(seed),
        "seed_validation": basin._validation(seed, current, snapshot), "timing": timing,
        "result": p3._result(package), "result_points": points.tolist(),
        "result_geometry": basin._geometry(points, set(pins)), "result_raw_curvature": _raw_curvature(points),
        "result_energy": basin._energy(current, points), "result_validation": basin._validation(points, current, snapshot),
        "trace": asdict(package.trace)}


def _distances(first, second):
    values = np.linalg.norm(np.asarray(first) - np.asarray(second), axis=1)
    return {"maximum": float(values.max()), "rms": float(np.sqrt(np.mean(values ** 2)))}


def _comparisons(rows):
    baseline = rows.get("BASELINE", rows["CURVATURE_ZERO"])["result_points"]
    shortcut = rows.get("SHORTCUT", rows["CURVATURE_ZERO"])["result_points"]
    for name, row in rows.items():
        row["distance_from_baseline"] = _distances(baseline, row["result_points"])
        row["distance_from_shortcut"] = _distances(shortcut, row["result_points"])


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    request, snapshot, capture = p3._capture(root, fiber, depsgraph); request = p3._override_cap(request, args.accepted_cap)
    planner = plan_reference_v43(request, snapshot, native_world=cached_native_collision_world_batch(request.colliders))
    direct, pins = _direct_reference(request); seed = _planner_seed(planner, pins, len(direct))
    started = perf_counter(); fixed, shortcut_stats = _shortcut_seed(request, planner, seed, pins, args.subdivisions)
    variants = BROAD_VARIANTS if args.suite == "broad" else SHORTCUT_ZERO_VARIANTS if args.suite == "shortcut-zero" else VARIANTS
    shortcut_stats["ms"] = _elapsed(started); rows = {name: _variant(name, use, scale, request, snapshot,
        (seed, fixed), pins, args.repeats) for name, use, scale in variants}; _comparisons(rows)
    routes = [np.asarray(row[key]) for row in rows.values() for key in ("seed_points", "result_points")]
    return {"experiment": "ROADMAP continuous shortcut and curvature ablation", "file": bpy.data.filepath,
        "file_sha256": common._file_hash(bpy.data.filepath), "fiber": fiber.id, "capture_ms": capture,
        "accepted_cap": args.accepted_cap, "subdivisions": args.subdivisions, "pin_indices": pins,
        "planner": {"mode": planner.mode.value, "branches": [span.branch.value for span in planner.spans]},
        "shortcut": shortcut_stats, "variants": rows, "nearby_triangles": p3._nearby(snapshot, routes)}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: {"termination": row["result"]["termination"], "valid": row["result_validation"]["valid"],
        "length": row["result_geometry"]["path_length"], "turn": row["result_geometry"]["worst_free_turn"],
        "ms": row["timing"]["median_ms"]} for name, row in record["variants"].items()}
    print("AF_V2_ROADMAP_CURVATURE", json.dumps({"shortcut": record["shortcut"], "variants": summary}), flush=True)


if __name__ == "__main__":
    main()
