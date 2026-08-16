"""Read-only Package 6 fixture qualification for a loaded Blender file."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy

from anthroforge.core.vcp.fiber_modes import is_loop_fiber
from anthroforge.core.vcp.v2 import build_triangle_snapshot
from anthroforge.core.vcp.v2.solver import _package5_planner
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _failure(fiber, reason):
    return {"id": fiber.id, "name": fiber.name, "eligible": False, "reason": str(reason)}


def _qualify(root, fiber, depsgraph, colliders, snapshot):
    if is_loop_fiber(fiber):
        return _failure(fiber, "loop fixture excluded from this open-Fiber experiment")
    try:
        anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
        request = bench._request(root, fiber, anchors, colliders); started = perf_counter()
        planner = _package5_planner(request, snapshot); elapsed = 1000.0 * (perf_counter() - started)
    except Exception as exc:
        return _failure(fiber, exc)
    return _qualified_row(fiber, request, planner, elapsed)


def _qualified_row(fiber, request, planner, elapsed):
    diag = planner.diagnostics
    return {"id": fiber.id, "name": fiber.name, "eligible": planner.succeeded,
            "reason": planner.message, "mode": planner.mode.value, "anchors": len(request.anchors),
            "nodes": request.settings.node_count, "steps": request.settings.max_accepted_steps,
            "surface_routing": bool(fiber.use_surface_routing), "segment_collisions": bool(fiber.use_segment_collisions),
            "planner_ms": elapsed, "pairs": diag.candidate_pairs, "tested": diag.tested_pairs}


def _record():
    root = bench._root(); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders = bench._colliders(bpy.context.scene, root, depsgraph); snapshot = build_triangle_snapshot(colliders)
    rows = [_qualify(root, fiber, depsgraph, colliders, snapshot) for fiber in root.af_vcp_system.fibers]
    return {"file": bpy.data.filepath, "root": root.name, "triangles": len(snapshot.triangles),
            "colliders": snapshot.source_count, "fibers": rows}


def main():
    args = _arguments(); record = _record(); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    eligible = [row["id"] for row in record["fibers"] if row["eligible"]]
    print("AF_P6_FIXTURES", json.dumps({"eligible": eligible, "count": len(eligible)}), flush=True)


if __name__ == "__main__":
    main()
