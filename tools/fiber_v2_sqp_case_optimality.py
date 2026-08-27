"""Run the span-SQP optimality diagnostic on a stored basin-test case."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
import fiber_v2_sqp_optimality_diagnostic as optimality
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--input", required=True); parser.add_argument("--case", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--accepted-cap", type=int, default=180)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _capture(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    request, snapshot, capture = p3._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    return fiber, p3._override_cap(request, args.accepted_cap), snapshot, capture


def _package(request, snapshot, points):
    package = solve_subfiber_sqp_fixed(request, snapshot=snapshot)
    result = replace(package.result, points=tuple(map(tuple, points)), validated=True)
    return replace(package, result=result)


def _record(args):
    source = json.loads(Path(args.input).read_text(encoding="utf-8")); case = source["cases"][args.case]
    fiber, request, snapshot, capture = _capture(args); package = _package(request, snapshot, case["result_points"])
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
        "fiber": fiber.id, "case": args.case, "capture_ms": capture,
        "analysis": optimality._analyze(request, snapshot, package)}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    analysis = record["analysis"]
    print("AF_V2_SQP_CASE_OPTIMALITY", json.dumps({"case": args.case,
        "classification": analysis["classification"], "kkt": analysis["kkt"],
        "spectrum": analysis["spectrum"]}, default=str), flush=True)


if __name__ == "__main__":
    main()
