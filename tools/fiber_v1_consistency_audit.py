"""Read-only V1 consistency audit for equivalent Blender Fiber fixtures."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=15); parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--surface-routing", choices=("preserve", "on", "off"), default="preserve")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest().upper()


def _geometry_digest(collider):
    digest = sha256(); digest.update(collider.owner_id.encode("utf-8"))
    digest.update(np.asarray(collider.vertices, dtype="<f8").tobytes())
    digest.update(np.asarray(collider.triangles, dtype="<i8").tobytes())
    return digest.hexdigest().upper()


def _rounded_digest(collider):
    digest = sha256(); vertices = np.round(np.asarray(collider.vertices, dtype="<f8"), 6)
    digest.update(vertices.tobytes()); digest.update(np.asarray(collider.triangles, dtype="<i8").tobytes())
    return digest.hexdigest().upper()


def _collider_rows(colliders):
    return [_collider_row(row) for row in colliders]


def _collider_row(collider):
    points = np.asarray(collider.vertices, dtype=np.float64)
    return {"owner": collider.owner_id, "vertices": len(points), "triangles": len(collider.triangles),
            "digest": _geometry_digest(collider), "rounded_1e6": _rounded_digest(collider),
            "minimum": points.min(axis=0).tolist(), "maximum": points.max(axis=0).tolist()}


def _settings(fiber):
    names = ("node_count", "iterations_interactive", "iterations_bake", "stretch_stiffness",
             "bend_stiffness", "collision_radius", "use_segment_collisions", "use_surface_routing",
             "use_warm_start", "solver_version", "topology_mode", "preview_planner_route")
    return {name: getattr(fiber, name, None) for name in names}


def _points_payload(points):
    values = np.asarray([tuple(point) for point in points], dtype=np.float64)
    length = float(np.linalg.norm(np.diff(values, axis=0), axis=1).sum()) if len(values) > 1 else 0.0
    return {"count": len(values), "length": length, "digest": sha256(values.tobytes()).hexdigest().upper()}


def _solve_once(root, fiber, depsgraph):
    solver = FiberSolver(); solver.clear_cache(fiber.id)
    started = perf_counter(); points = solver.solve_points(root, fiber, bpy.context.scene, depsgraph, bake=False)
    return 1000.0 * (perf_counter() - started), _points_payload(points)


def _timings(root, fiber, depsgraph, warmups, repeats):
    for _index in range(max(0, warmups)):
        _solve_once(root, fiber, depsgraph)
    rows = [_solve_once(root, fiber, depsgraph) for _index in range(max(1, repeats))]
    return [row[0] for row in rows], [row[1] for row in rows]


def _summary(values):
    ordered = sorted(values); p95 = ordered[min(len(ordered) - 1, int(np.ceil(.95 * len(ordered))) - 1)]
    return {"median_ms": statistics.median(values), "p95_ms": p95, "min_ms": min(values), "max_ms": max(values)}


def _planner(root, fiber, anchors, depsgraph):
    result = bench._v1_plan(root, fiber, anchors, depsgraph)
    return {"mode": result.mode, "active_ids": list(result.active_ids), "route": _points_payload(result.points)}


def _apply_override(fiber, value):
    if value == "preserve":
        return
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        fiber.use_surface_routing = value == "on"


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); _apply_override(fiber, args.surface_routing)
    depsgraph = bpy.context.evaluated_depsgraph_get(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    anchors, legacy = bench._open_anchors(root, fiber, depsgraph); times, routes = _timings(
        root, fiber, depsgraph, args.warmups, args.repeats)
    collider_rows = _collider_rows(colliders); stored = persisted_fiber_points(bpy.context.scene, root.name, fiber.id)
    inputs = {"settings": _settings(fiber), "anchors": [vars(row) for row in anchors], "colliders": collider_rows}
    return {"file": bpy.data.filepath, "fiber": fiber.id, "input_digest": _digest(inputs), "inputs": inputs,
            "planner": _planner(root, fiber, legacy, depsgraph), "stored": _points_payload(stored or ()),
            "timing": _summary(times), "times_ms": times, "routes": routes}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    print("AF_V1_AUDIT", json.dumps({"input": record["input_digest"], "timing": record["timing"],
          "routes": sorted({row["digest"] for row in record["routes"]})}), flush=True)


if __name__ == "__main__":
    main()
