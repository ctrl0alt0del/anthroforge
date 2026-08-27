"""Opt-in full iteration trace for the corrected span-SQP experiment."""

import json
from dataclasses import asdict
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
from anthroforge.core.vcp.v2.production import clear_v2_production_caches
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = common.argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--accepted-cap", type=int, default=60)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _solve(request, snapshot, diagnostic=False):
    return solve_subfiber_sqp_fixed(request, snapshot=snapshot, diagnostic_trace=diagnostic)


def _timed(request, snapshot, diagnostic=False):
    started = perf_counter(); package = _solve(request, snapshot, diagnostic)
    return 1000.0 * (perf_counter() - started), package


def _samples(request, snapshot, repeats):
    rows = []
    for _index in range(max(1, repeats)):
        clear_v2_production_caches(); rows.append(_timed(request, snapshot)[0])
    return tuple(rows)


def _timing(samples, traced_ms):
    base = median(samples); overhead = 100.0 * (traced_ms - base) / max(base, 1.0e-12)
    return {"untraced_samples_ms": samples, "untraced_median_ms": base,
            "traced_ms": traced_ms, "trace_overhead_percent": overhead}


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); v1 = p3._v1(root, fiber, depsgraph)
    request, snapshot, capture = p3._capture(root, fiber, depsgraph)
    return root, fiber, p3._override_cap(request, args.accepted_cap), snapshot, capture, v1


def _record(args):
    _root, fiber, request, snapshot, capture, v1 = _capture(args)
    samples = _samples(request, snapshot, args.repeats); clear_v2_production_caches()
    traced_ms, package = _timed(request, snapshot, True)
    return _payload(fiber, request, snapshot, capture, v1, package,
                    _timing(samples, traced_ms))


def _payload(fiber, request, snapshot, capture, v1, package, timing):
    path = bpy.data.filepath
    return {"file": path, "file_sha256": common._file_hash(path), "fiber": fiber.id,
        "node_count": request.settings.node_count, "accepted_step_cap": request.settings.max_accepted_steps,
        "capture_ms": capture, "triangles": len(snapshot.triangles), "timing": timing,
        "v1": v1, "result": p3._result(package), "trace": asdict(package.trace),
        "final_contacts": p3._contacts(request, package.result.points),
        "visual": p3._visual(request, v1, package, snapshot)}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    info = record["timing"] | {"termination": record["result"]["termination"]}
    print("AF_V2_SQP_DIAGNOSTIC", json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
