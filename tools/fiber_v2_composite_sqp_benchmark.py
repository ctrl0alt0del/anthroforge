"""Ablate feasible tangential, composite, and SOC Fiber SQP steps."""

import json
from dataclasses import asdict
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
from anthroforge.core.vcp.v2.contact_core import V2ContactExperiment
from anthroforge.core.vcp.v2.production import clear_v2_production_caches
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


VARIANTS = ("BASE", "TANGENTIAL", "COMPOSITE", "COMPOSITE_SOC")


def _args():
    parser = common.argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--accepted-cap", type=int, default=120)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _solve(request, snapshot, variant, diagnostic=False):
    experiment = V2ContactExperiment(sqp_variant=variant)
    return solve_subfiber_sqp_fixed(request, snapshot=snapshot, diagnostic_trace=diagnostic,
                                    experiment=experiment)


def _sample(request, snapshot, variant, cold):
    if cold: clear_v2_production_caches()
    started = perf_counter(); package = _solve(request, snapshot, variant)
    return 1000.0 * (perf_counter() - started), package


def _samples(request, snapshot, variant, repeats, cold):
    return tuple(_sample(request, snapshot, variant, cold) for _index in range(max(1, repeats)))


def _timing(rows):
    values = tuple(row[0] for row in rows)
    return {"median_ms": median(values), "minimum_ms": min(values), "maximum_ms": max(values),
            "samples_ms": values}


def _turns(points):
    values = np.asarray(points); before = values[1:-1] - values[:-2]; after = values[2:] - values[1:-1]
    scale = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
    cosine = np.divide(np.sum(before * after, axis=1), scale, out=np.ones(len(scale)), where=scale > 1e-20)
    return np.r_[0.0, np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))), 0.0]


def _free_nodes(package, count):
    pins = {value for span in package.trace.spans for value in (span.first_node, span.last_node)}
    return tuple(index for index in range(1, count - 1) if index not in pins)


def _geometry(package):
    values = np.asarray(package.result.points); turns = _turns(values)
    free = _free_nodes(package, len(values)); worst = max(free, key=lambda index: turns[index])
    lengths = np.linalg.norm(np.diff(values, axis=0), axis=1)
    return {"path_length": float(np.sum(lengths)), "worst_free_node": int(worst),
        "worst_free_turn": float(turns[worst]), "free_turn_p95": float(np.percentile(turns[list(free)], 95)),
        "segment_cv": float(np.std(lengths) / max(np.mean(lengths), 1e-12)), "turns": tuple(map(float, turns))}


def _stats(package):
    output = {}
    for span in package.trace.spans:
        for key, value in span.experiment_stats: output[key] = output.get(key, 0) + value
    return output


def _variant(request, snapshot, variant, repeats):
    clear_v2_production_caches(); _solve(request, snapshot, variant)
    cold = _samples(request, snapshot, variant, repeats, True)
    warm = _samples(request, snapshot, variant, repeats, False)
    clear_v2_production_caches(); traced = _solve(request, snapshot, variant, True)
    return {"cold": _timing(cold), "warm": _timing(warm), "result": p3._result(traced),
        "geometry": _geometry(traced), "experiment_stats": _stats(traced),
        "trace": asdict(traced.trace), "contacts": p3._contacts(request, traced.result.points)}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    return fiber, p3._override_cap(request, args.accepted_cap), snapshot, capture


def _deltas(rows):
    base = np.asarray(rows["BASE"]["result"]["points"]); output = {}
    for name, row in rows.items():
        delta = np.linalg.norm(np.asarray(row["result"]["points"]) - base, axis=1)
        output[name] = {"maximum": float(np.max(delta)), "rms": float(np.sqrt(np.mean(delta ** 2)))}
    return output


def _payload(fiber, request, snapshot, capture, rows):
    path = bpy.data.filepath; routes = tuple(np.asarray(row["result"]["points"]) for row in rows.values())
    return {"file": path, "file_sha256": common._file_hash(path), "fiber": fiber.id,
        "node_count": request.settings.node_count, "accepted_cap": request.settings.max_accepted_steps,
        "capture_ms": capture, "triangles": len(snapshot.triangles), "variants": rows,
        "deltas_from_base": _deltas(rows), "nearby_triangles": p3._nearby(snapshot, routes)}


def main():
    args = _args(); fiber, request, snapshot, capture = _capture(args)
    rows = {name: _variant(request, snapshot, name, args.repeats) for name in VARIANTS}
    record = _payload(fiber, request, snapshot, capture, rows); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {name: (round(row["warm"]["median_ms"], 2), row["result"]["termination"],
        round(row["geometry"]["worst_free_turn"], 2)) for name, row in rows.items()}
    print("AF_V2_COMPOSITE_SQP", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
