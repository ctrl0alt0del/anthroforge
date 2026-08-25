"""Interleaved BASE, whole-SQP, and span-SQP Blender benchmark."""

import json
from pathlib import Path
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_production3_benchmark as p3
from anthroforge.core.vcp.v2.production import clear_v2_production_caches
from anthroforge.tools import fiber_v2_planner_benchmark as common


CONTROLLERS = ("BASE", "SQP", "SPAN_SQP", "SPAN_SQP_FIXED")


def _args():
    parser = common.argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--accepted-cap", type=int, default=60)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _controller(request, snapshot, name, repeats):
    call = lambda: p3._solve(request, snapshot, name)
    clear_v2_production_caches(); warmup = call()
    cold = p3._measure(call, repeats, True); warm = p3._measure(call, repeats, False)
    return {"warmup": p3._result(warmup), "cold": cold, "warm": warm}


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); request, snapshot, capture = p3._capture(root, fiber, depsgraph)
    request = p3._override_cap(request, args.accepted_cap)
    rows = {name: _controller(request, snapshot, name, args.repeats) for name in CONTROLLERS}
    return _payload(args, fiber, request, snapshot, capture, rows)


def _payload(args, fiber, request, snapshot, capture, rows):
    path = bpy.data.filepath
    return {"file": path, "file_sha256": common._file_hash(path), "fiber": fiber.id,
            "node_count": request.settings.node_count, "accepted_cap": args.accepted_cap,
            "capture_ms": capture, "triangles": len(snapshot.triangles), "controllers": rows}


def main():
    args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    summary = {key: round(value["warm"]["median_ms"], 2) for key, value in record["controllers"].items()}
    print("AF_V2_SUBFIBER", json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
