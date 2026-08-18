"""Audit every open Fiber through V2.4 in one read-only Blender file."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot_known,
    cached_native_collision_world_batch, solve_v24, v22_snapshot_key)
from anthroforge.tools import fiber_v24_benchmark as v24
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge
    anthroforge.register()


def _source(root, fiber):
    proxy = common._proxy(root, fiber.id)
    return common._curve_points(proxy) if proxy else np.empty((0, 3), dtype=np.float64)


def _length(points):
    values = np.asarray(points, dtype=np.float64)
    return float(np.linalg.norm(np.diff(values, axis=0), axis=1).sum()) if len(values) > 1 else 0.0


def _turns(points):
    edges = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    if len(edges) < 2: return 0.0, 0.0
    unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    angles = np.arccos(np.clip(np.sum(unit[:-1] * unit[1:], axis=1), -1.0, 1.0))
    return float(np.sum(angles)), float(np.max(angles))


def _resample(points, count=128):
    values = np.asarray(points, dtype=np.float64)
    if len(values) < 2: return values
    arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(values, axis=0), axis=1))]
    if arc[-1] <= 1.0e-12: return np.repeat(values[:1], count, axis=0)
    targets = np.linspace(0.0, arc[-1], count)
    return np.column_stack([np.interp(targets, arc, values[:, axis]) for axis in range(3)])


def _delta(first, second):
    if len(first) < 2 or len(second) < 2: return {"mean": None, "max": None}
    values = np.linalg.norm(_resample(first) - _resample(second), axis=1)
    return {"mean": float(np.mean(values)), "max": float(np.max(values))}


def _path_metrics(points):
    total, maximum = _turns(points)
    return {"count": len(points), "length": _length(points),
            "total_turn_radians": total, "max_turn_radians": maximum}


def _paths(source, package):
    planner = np.asarray(package.planner.reference, dtype=np.float64).reshape((-1, 3))
    final = np.asarray(package.result.points, dtype=np.float64).reshape((-1, 3))
    return source, planner, final


def _visual(snapshot, paths, anchors):
    active = tuple(row for row in paths if len(row))
    triangles = p41._nearby_faces(snapshot, active) if active else np.empty((0, 3, 3))
    return {"source": paths[0].tolist(), "planner": paths[1].tolist(),
            "v24": paths[2].tolist(), "anchors": [list(row.point) for row in anchors],
            "nearby_triangles": triangles.tolist()}


def _result_payload(package):
    result, planner = package.result, package.planner
    return {"termination": result.termination.value, "validated": result.validated,
            "route": result.route_branch, "message": result.message,
            "diagnostics": vars(result.diagnostics), "trace": vars(package.trace),
            "planner_diagnostics": vars(planner.diagnostics)}


def _solved_row(fiber, source, request, package, snapshot, elapsed):
    paths = _paths(source, package); metrics = [_path_metrics(row) for row in paths]
    return {"fiber": fiber.id, "name": fiber.name, "solver_version": int(fiber.solver_version),
            "node_count": int(fiber.node_count), "collision_radius": float(fiber.collision_radius),
            "elapsed_ms": elapsed, "result": _result_payload(package),
            "metrics": dict(zip(("source", "planner", "v24"), metrics)),
            "planner_to_final": _delta(paths[1], paths[2]),
            "source_to_final": _delta(paths[0], paths[2]),
            "visual": _visual(snapshot, paths, request.anchors), "error": ""}


def _error_row(fiber, source, error, snapshot):
    paths = (source, np.empty((0, 3)), np.empty((0, 3)))
    return {"fiber": fiber.id, "name": fiber.name, "solver_version": int(fiber.solver_version),
            "node_count": int(fiber.node_count), "collision_radius": float(fiber.collision_radius),
            "elapsed_ms": 0.0, "result": {"termination": "INVALID_ATTACHMENT",
            "validated": False, "route": "", "message": str(error)},
            "metrics": {"source": _path_metrics(source)}, "planner_to_final": {},
            "source_to_final": {}, "visual": _visual(snapshot, paths, ()), "error": str(error)}


def _row(root, fiber, depsgraph, colliders, snapshot):
    source = _source(root, fiber)
    try:
        anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
        request = common._request(root, fiber, anchors, colliders); started = perf_counter()
        package = solve_v24(request, snapshot=snapshot)
        return _solved_row(fiber, source, request, package, snapshot, _ms(started))
    except Exception as error:
        return _error_row(fiber, source, error, snapshot)


def _record():
    root = common._root(); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders, capture_ms = _colliders(root, depsgraph)
    world = cached_native_collision_world_batch(colliders, _snapshot_key(root, colliders))
    snapshot = build_triangle_snapshot_known(colliders, world.closed_flags)
    rows = [_row(root, fiber, depsgraph, colliders, snapshot) for fiber in root.af_vcp_system.fibers]
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
            "root": root.name, "capture_ms": capture_ms, "fibers": rows}


def _colliders(root, depsgraph):
    started = perf_counter(); rows, _digest = v24._native_colliders(bpy.context.scene, root, depsgraph)
    return rows, _ms(started)


def _snapshot_key(root, colliders):
    fiber = root.af_vcp_system.fibers[0]
    anchors, _legacy = common._open_anchors(root, fiber, bpy.context.evaluated_depsgraph_get())
    return v22_snapshot_key(common._request(root, fiber, anchors, colliders))


def _ms(started):
    return 1000.0 * (perf_counter() - started)


def main():
    _ensure_addon(); args = _args(); record = _record(); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    counts = {key: sum(row["result"]["termination"] == key for row in record["fibers"])
              for key in {row["result"]["termination"] for row in record["fibers"]}}
    print("AF_V24_VISUAL", json.dumps({"fibers": len(record["fibers"]), "counts": counts}), flush=True)


if __name__ == "__main__":
    main()
