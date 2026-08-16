"""Read-only real-Blender benchmark for Package 5 versus the V1 solver."""

import argparse
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot, solve_package5, solve_package51,
                                     structural_energy, validate_static_clearance)
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=3)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _v1_solve(root, fiber, depsgraph):
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    solver = FiberSolver(); solver.clear_cache(fiber.id)
    return solver.solve_points(root, fiber, bpy.context.scene, depsgraph, bake=False)


def _timed(call, repeats):
    values, times = [], []
    for _index in range(max(1, repeats)):
        started = perf_counter(); values.append(call()); times.append(1000.0 * (perf_counter() - started))
    return times, values


def _summary(values):
    ordered = sorted(values); index = min(len(ordered) - 1, int(np.ceil(.95 * len(ordered))) - 1)
    return {"median_ms": statistics.median(values), "p95_ms": ordered[index], "max_ms": max(values)}


def _metrics(points):
    values = np.asarray(points, dtype=np.float64)
    edges = np.diff(values, axis=0); bends = np.diff(values, n=2, axis=0)
    return {"count": len(values), "length": float(np.linalg.norm(edges, axis=1).sum()),
            "curvature_l2": float(np.sum(bends * bends)), "points": values.tolist()}


def _validation(points, snapshot, request, contacts):
    return validate_static_clearance(points, snapshot, request.collision_policy.collision_radius,
                                     contacts, slack=request.tolerances.clearance_slack)


def _validation_payload(value):
    return {"valid": value.valid, "node_residual": value.node_residual,
            "edge_residual": value.edge_residual, "violating_nodes": list(value.violating_nodes),
            "violating_edges": list(value.violating_edges), "contained_nodes": list(value.contained_nodes)}


def _v1_payload(times, points, request, snapshot):
    values = np.asarray([tuple(point) for point in points], dtype=np.float64)
    checked = bench._strict_validation(values, request.anchors, snapshot,
                                       request.collision_policy.collision_radius,
                                       request.tolerances.clearance_slack)
    return {"timing": _summary(times), "route": _metrics(values),
            "validation": _validation_payload(checked)}


def _p5_payload(times, rows, request, snapshot):
    item = rows[-1]; points = np.asarray(item.result.points); checked = _validation(
        points, snapshot, request, item.planner.contacts)
    reference = np.asarray(item.planner.reference); before = structural_energy(reference, reference, request.settings)
    after = structural_energy(points, reference, request.settings)
    return {"timing": _summary(times), "termination": item.result.termination.value,
            "validated": item.result.validated, "message": item.result.message,
            "route_branch": item.result.route_branch, "route": _metrics(points),
            "planner_reference": _metrics(reference), "validation": _validation_payload(checked),
            "diagnostics": vars(item.result.diagnostics), "trace": vars(item.trace),
            "structural_energy_before": before.total, "structural_energy_after": after.total,
            "deterministic": _deterministic(rows)}


def _deterministic(rows):
    first = rows[0].result
    return all(row.result.points == first.points and row.result.termination == first.termination
               for row in rows[1:])


def _visual(source, v1, p5, p51, snapshot):
    planner = np.asarray(p5.planner.reference); solved = np.asarray(p5.result.points)
    optimized = np.asarray(p51.result.points); routes = (np.asarray(source), np.asarray(v1), planner, solved, optimized)
    nearby = p41._nearby_faces(snapshot, routes)
    return {"source": np.asarray(source).tolist(), "v1": np.asarray(v1).tolist(),
            "package43": planner.tolist(), "package5": solved.tolist(),
            "package51": optimized.tolist(),
            "nearby_triangles": nearby.tolist()}


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); capture = perf_counter()
    colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); capture_ms = 1000.0 * (perf_counter() - capture)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
    request = bench._request(root, fiber, anchors, colliders); solve_package5(request, snapshot); solve_package51(request, snapshot)
    v1_times, v1_rows = _timed(lambda: _v1_solve(root, fiber, depsgraph), args.repeats)
    p5_times, p5_rows = _timed(lambda: solve_package5(request, snapshot), args.repeats)
    p51_times, p51_rows = _timed(lambda: solve_package51(request, snapshot), args.repeats)
    return _payload(root, fiber, request, snapshot, capture_ms, v1_times, v1_rows,
                    p5_times, p5_rows, p51_times, p51_rows)


def _payload(root, fiber, request, snapshot, capture, v1_times, v1_rows,
             p5_times, p5_rows, p51_times, p51_rows):
    source = tuple(anchor.point for anchor in request.anchors)
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "root": root.name, "fiber_id": fiber.id, "fiber_name": fiber.name,
            "triangles": len(snapshot.triangles), "colliders": snapshot.source_count,
            "snapshot_capture_ms": capture, "repeats": len(p5_times),
            "v1": _v1_payload(v1_times, v1_rows[-1], request, snapshot),
            "package5": _p5_payload(p5_times, p5_rows, request, snapshot),
            "package51": _p5_payload(p51_times, p51_rows, request, snapshot),
            "visual": _visual(source, v1_rows[-1], p5_rows[-1], p51_rows[-1], snapshot)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PACKAGE5", json.dumps({"v1": record["v1"]["timing"],
          "package5": record["package5"]["timing"],
          "package51": record["package51"]["timing"],
          "termination": record["package51"]["termination"]}), flush=True)


if __name__ == "__main__":
    main()
