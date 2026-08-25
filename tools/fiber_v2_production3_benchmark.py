"""Read-only V1 versus production-3 Fiber qualification benchmark."""

import json
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2.collision import cached_native_collision_world
from anthroforge.core.vcp.v2.contact_core import _direct_reference, solve_contact_core
from anthroforge.core.vcp.v2.production import clear_v2_production_caches, solve_v2
from anthroforge.core.vcp.v2.subfiber_sqp import solve_subfiber_sqp, solve_subfiber_sqp_fixed
from anthroforge.tools import fiber_v2_package5_benchmark as p5
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _args():
    parser = common.argparse.ArgumentParser(); parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--accepted-cap", type=int, default=0)
    modes = ("BASE", "TRUST", "ANDERSON", "RECOVERY", "SQP", "SPAN_SQP",
             "SPAN_SQP_FIXED", "ALL")
    parser.add_argument("--controller", choices=modes, default="BASE")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _timed(call):
    started = perf_counter(); value = call()
    return 1000.0 * (perf_counter() - started), value


def _measure(call, repeats, cold):
    rows = []
    for _index in range(max(1, repeats)):
        if cold: clear_v2_production_caches()
        rows.append(_timed(call))
    return _summary(rows)


def _summary(rows):
    times = [row[0] for row in rows]; result = rows[-1][1]
    return {"median_ms": median(times), "min_ms": min(times), "max_ms": max(times),
            "result": _result(result), "trace": _trace_payload(result.trace)}


def _trace_payload(trace):
    return asdict(trace) if is_dataclass(trace) else vars(trace)


def _result(package):
    value = package.result
    return {"termination": value.termination.value, "validated": value.validated,
            "route": value.route_branch, "message": value.message,
            "points": value.points, "diagnostics": vars(value.diagnostics)}


def _v1(root, fiber, depsgraph):
    elapsed, points = _timed(lambda: p5._v1_solve(root, fiber, depsgraph))
    return {"ms": elapsed, "points": tuple(tuple(value) for value in points)}


def _capture(root, fiber, depsgraph):
    started = perf_counter(); colliders = common._colliders(bpy.context.scene, root, depsgraph)
    anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
    request = common._request(root, fiber, anchors, colliders)
    return request, common.build_triangle_snapshot(colliders), 1000.0 * (perf_counter() - started)


def _override_cap(request, cap):
    if cap <= 0: return request
    settings = replace(request.settings, max_accepted_steps=cap)
    return replace(request, settings=settings)


def _solve(request, snapshot, controller):
    if controller == "SPAN_SQP_FIXED": return solve_subfiber_sqp_fixed(request, snapshot=snapshot)
    if controller == "SPAN_SQP": return solve_subfiber_sqp(request, snapshot=snapshot)
    if controller != "BASE": return solve_contact_core(request, snapshot=snapshot,
        use_acceleration=controller in {"ANDERSON", "ALL"},
        use_adaptive_trust=controller in {"TRUST", "ALL"},
        use_stall_recovery=controller in {"RECOVERY", "ALL"},
        use_filter_sqp=controller == "SQP")
    return solve_v2(request, snapshot=snapshot)


def _nearby(snapshot, routes):
    usable = tuple(row for row in routes if len(row))
    return p41._nearby_faces(snapshot, usable).tolist() if usable else []


def _visual(request, v1, package, snapshot):
    direct = _direct_reference(request)[0]; planner = np.asarray(package.planner.reference)
    solved = np.asarray(package.result.points); legacy = np.asarray(v1["points"])
    routes = (direct, planner, legacy, solved)
    return {"direct": direct.tolist(), "planner": planner.tolist(), "v1": legacy.tolist(),
            "v2": solved.tolist(), "anchors": [{"point": list(row.point), "owner": row.owner_id,
            "role": row.role.value} for row in request.anchors],
            "nearby_triangles": _nearby(snapshot, routes)}


def _contacts(request, points):
    values = np.asarray(points); _q, pins = _direct_reference(request)
    owner_map = {index: row.owner_id for index, row in zip(pins, request.anchors)}
    edges = tuple((index, index + 1) for index in range(len(values) - 1))
    owners = tuple((owner_map.get(a, ""), owner_map.get(b, "")) for a, b in edges)
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    batch = cached_native_collision_world(request.colliders).contact_pairs(
        values, edges, owners, _contact_span(values, pins, radius, slack),
        radius + max(4 * slack, .25 * radius))
    return [_contact_payload(row, radius) for row in batch.pairs if row.contained or row.distance < radius]


def _contact_span(points, pins, radius, slack):
    lengths = []
    for pin in pins:
        if pin: lengths.append(np.linalg.norm(points[pin] - points[pin - 1]))
        if pin + 1 < len(points): lengths.append(np.linalg.norm(points[pin + 1] - points[pin]))
    return max(4 * slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)


def _contact_payload(row, radius):
    gap = -(row.distance + radius) if row.contained else row.distance - radius
    return {"edge": row.edge, "factor": row.factor, "collider": row.collider_id,
            "face": row.face, "contained": row.contained, "distance": row.distance, "gap": gap}


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); v1 = _v1(root, fiber, depsgraph)
    request, snapshot, capture_ms = _capture(root, fiber, depsgraph)
    request = _override_cap(request, args.accepted_cap)
    clear_v2_production_caches(); warmup = _solve(request, snapshot, args.controller)
    cold = _measure(lambda: _solve(request, snapshot, args.controller), args.repeats, True)
    warm = _measure(lambda: _solve(request, snapshot, args.controller), args.repeats, False)
    return _payload(args, root, fiber, request, snapshot, capture_ms, v1, warmup, cold, warm)


def _payload(args, root, fiber, request, snapshot, capture, v1, warmup, cold, warm):
    path = bpy.data.filepath; package = _solve(request, snapshot, args.controller)
    return {"file": path, "file_sha256": common._file_hash(path), "fiber": fiber.id,
            "fiber_name": fiber.name, "node_count": request.settings.node_count,
            "accepted_step_cap": request.settings.max_accepted_steps,
            "colliders": snapshot.source_count, "triangles": len(snapshot.triangles),
            "collider_ranges": [list(row[:6]) for row in snapshot.collider_ranges],
            "capture_ms": capture, "v1": v1, "warmup": _result(warmup),
            "controller": args.controller,
            "v2_cold": cold, "v2_warm": warm,
            "final_contacts": _contacts(request, package.result.points),
            "visual": _visual(request, v1, package, snapshot)}


def main():
    args = _args(); output = Path(args.output); record = _record(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PRODUCTION3", json.dumps({"fiber": record["fiber"], "v1_ms": record["v1"]["ms"],
          "cold_ms": record["v2_cold"]["median_ms"], "warm_ms": record["v2_warm"]["median_ms"],
          "termination": record["v2_warm"]["result"]["termination"]}), flush=True)


if __name__ == "__main__":
    main()
