"""Probe whole-span collision-safe interpolation through authored Fiber pins."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import solve_v24
from anthroforge.core.vcp.v2 import solver as p5
from anthroforge.core.vcp.v2 import solver_pin_smoothing as smoothing
from anthroforge.core.vcp.v2.pin_smoothing_geometry import _arc_parameter, _hermite, turn_metrics
from anthroforge.tools import fiber_pin_smoothing_benchmark as benchmark
from anthroforge.tools import fiber_v25_branch2_sweep as base


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--fiber-id", default="FIBER_2")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _state(request, snapshot, package):
    live = SimpleNamespace(request=request, planner=package.planner, snapshot=snapshot,
                           points=np.asarray(package.result.points), pair_cache=p5.V2SweepPairCache())
    return smoothing._smoothing_state(live)


def _directions(points):
    edges = np.diff(points, axis=0); unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    rows = np.vstack((unit[0], unit[:-1] + unit[1:], unit[-1]))
    return rows / np.maximum(np.linalg.norm(rows, axis=1)[:, None], 1.0e-12)


def _spline(reference, pins, strength, parameter_mode):
    indices = np.asarray(tuple(pins), dtype=np.int64); anchors = reference[indices]; tangents = _directions(anchors)
    output = reference.copy()
    for span, (left, right) in enumerate(zip(indices[:-1], indices[1:])):
        arc, length = _arc_parameter(reference[left:right + 1])
        parameter = arc if parameter_mode == "arc" else np.linspace(0.0, 1.0, right-left+1)
        scale = float(strength) * length
        output[left:right + 1] = _hermite(anchors[span], anchors[span + 1], scale*tangents[span], scale*tangents[span + 1], parameter)
    output[indices] = anchors; return output


def _owner(state):
    owners = {row.owner_id for row in state.request.anchors if row.owner_id}
    return next(iter(owners)) if len(owners) == 1 else ""


def _movable(state):
    rows = np.arange(len(state.points), dtype=np.int64); pins = np.asarray(tuple(state.pins), dtype=np.int64)
    return rows[~np.isin(rows, pins)]


def _project_tangent(state, candidate, world):
    indices = _movable(state); normals = p5._unit_rows(world.nearest(state.reference[indices])[1])
    delta = candidate[indices] - state.reference[indices]
    candidate[indices] = state.reference[indices] + delta - np.sum(delta*normals, axis=1)[:, None]*normals
    return candidate


def _project_offset(state, candidate, world, factor):
    indices = _movable(state); nearest = world.nearest(candidate[indices])
    direction = p5._contact_directions(candidate[indices], *nearest[:3], nearest[4])
    radius = float(factor) * state.request.collision_policy.collision_radius
    candidate[indices] = nearest[0] + radius * direction; return candidate


def _project_same_side(state, candidate, world, factor):
    indices = _movable(state); reference = world.nearest(state.reference[indices]); nearest = world.nearest(candidate[indices])
    side = p5._contact_directions(state.reference[indices], *reference[:3], reference[4])
    direction = p5._unit_rows(nearest[1]); flip = np.sum(direction*side, axis=1) < 0.0
    direction[flip] *= -1.0; radius = float(factor) * state.request.collision_policy.collision_radius
    candidate[indices] = nearest[0] + radius * direction; return candidate


def _candidate(state, strength, parameter_mode, projection, offset):
    result = _spline(state.reference, tuple(state.pins), strength, parameter_mode)
    world = state.owner_worlds.get(_owner(state))
    if world is not None and projection in ("tangent", "offset"): result = _project_tangent(state, result, world)
    if world is not None and projection == "offset": result = _project_offset(state, result, world, offset)
    if world is not None and projection == "same_side": result = _project_same_side(state, result, world, offset)
    p5._restore_pins(result, state.pins); return result


def _trial(state, strength, parameter_mode, projection, offset):
    candidate = _candidate(state, strength, parameter_mode, projection, offset)
    envelope = p5._waypoint_envelope(state.points, (candidate,))
    started = perf_counter(); step = p5._safe_step_p51(state, state.points, candidate, envelope); elapsed = p5._elapsed(started)
    fraction = p5._backed_fraction(step.safe_step) if step.valid else 0.0
    proposed = p5._interpolate(state.points, candidate, fraction); p5._restore_pins(proposed, state.pins)
    checked = p5._validate(proposed, state.request, state.planner, state.snapshot)
    return _row(state, strength, parameter_mode, projection, offset, candidate, proposed, step, checked, elapsed)


def _lift_directions(state, world):
    nearest = world.nearest(state.points); rows = p5._contact_directions(state.points, *nearest[:3], nearest[4])
    rows[np.asarray(tuple(state.pins), dtype=np.int64)] = 0.0; return rows


def _curved_trial(state, strength, lift, segments=4):
    candidate = _candidate(state, strength, "uniform", "tangent", 0.0); world = state.owner_worlds.get(_owner(state))
    directions = _lift_directions(state, world); source = state.points.copy(); steps, pairs, tested, elapsed = [], 0, 0, 0.0
    waypoints = _lifted_waypoints(state, candidate, directions, lift, segments)
    envelope = p5._waypoint_envelope(state.points, waypoints)
    for target in waypoints:
        source, step, cost = _advance(state, source, target, envelope); elapsed += cost
        steps.append(float(step.safe_step)); pairs += int(step.candidate_pairs); tested += int(step.tested_pairs)
        if not step.valid or step.safe_step < 1.0 - 1.0e-12: break
    return _curved_row(state, strength, lift, segments, candidate, source, steps, pairs, tested, elapsed)


def _lifted_waypoints(state, candidate, directions, lift, segments):
    radius = float(lift) * state.request.collision_policy.collision_radius; rows = []
    for factor in np.linspace(1.0 / int(segments), 1.0, int(segments)):
        row = p5._interpolate(state.points, candidate, factor)
        row += radius*np.sin(np.pi*factor)*directions; p5._restore_pins(row, state.pins); rows.append(row)
    return tuple(rows)


def _advance(state, source, target, envelope):
    started = perf_counter(); step = p5._safe_step_p51(state, source, target, envelope); elapsed = p5._elapsed(started)
    fraction = p5._backed_fraction(step.safe_step) if step.valid else 0.0
    proposed = p5._interpolate(source, target, fraction); p5._restore_pins(proposed, state.pins)
    return proposed, step, elapsed


def _curved_row(state, strength, lift, segments, candidate, proposed, steps, pairs, tested, elapsed):
    checked = p5._validate(proposed, state.request, state.planner, state.snapshot)
    target = p5._validate(candidate, state.request, state.planner, state.snapshot)
    return {"strength": strength, "parameter": "uniform", "projection": "curved", "offset": lift,
            "segments": segments,
            "candidate": _metrics(candidate), "accepted": _metrics(proposed), "safe_steps": steps,
            "candidate_valid": bool(target.valid), "valid": bool(checked.valid), "ccd_ms": elapsed,
            "pairs": pairs, "tested": tested, "max_displacement": float(np.max(np.linalg.norm(proposed-state.points, axis=1))),
            "points": proposed.tolist()}


def _row(state, strength, parameter_mode, projection, offset, candidate, proposed, step, checked, elapsed):
    target = p5._validate(candidate, state.request, state.planner, state.snapshot)
    return {"strength": strength, "parameter": parameter_mode, "projection": projection, "offset": offset,
            "candidate": _metrics(candidate), "accepted": _metrics(proposed),
            "safe_step": float(step.safe_step), "candidate_valid": bool(target.valid),
            "valid": bool(checked.valid), "ccd_ms": elapsed,
            "pairs": int(step.candidate_pairs), "tested": int(step.tested_pairs),
            "max_displacement": float(np.max(np.linalg.norm(proposed-state.points, axis=1))),
            "points": proposed.tolist()}


def _metrics(points):
    maximum, p95, total = turn_metrics(points)
    return {"max_turn_deg": maximum, "p95_turn_deg": p95, "total_turn_deg": total,
            "length": float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1))),
            "worst_turns": _worst_turns(points)}


def _worst_turns(points):
    edges = np.diff(points, axis=0); unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    turns = np.degrees(np.arccos(np.clip(np.sum(unit[:-1]*unit[1:], axis=1), -1.0, 1.0)))
    order = np.argsort(turns)[-8:][::-1]
    return [[int(index + 1), float(turns[index])] for index in order]


def _trials(state):
    rows = []
    for strength in (.25, .5, .75, 1.0, 1.25):
        for parameter_mode in ("arc", "uniform"):
            for projection in ("none", "tangent", "offset", "same_side"):
                for offset in ((1.0, 1.5, 2.0) if projection in ("offset", "same_side") else (0.0,)):
                    rows.append(_trial(state, strength, parameter_mode, projection, offset))
    rows += [_curved_trial(state, strength, lift, segments) for strength in (.75, 1.0, 1.25, 1.5, 1.75, 2.0)
             for lift in (1.0, 2.0, 4.0) for segments in (2, 3, 4)]
    return sorted(rows, key=lambda row: (not row["valid"], row["accepted"]["p95_turn_deg"], row["accepted"]["max_turn_deg"]))


def _record(args):
    root = base.common._root(); fiber = base.common._fiber(root, args.fiber_id)
    request, snapshot, anchors = base._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    package = solve_v24(request, snapshot); state = _state(request, snapshot, package); rows = _trials(state)
    stored = np.asarray(benchmark.base._source(root, fiber), dtype=np.float64)
    baseline = SimpleNamespace(result=SimpleNamespace(points=state.points)); visual = base._visual(root, fiber, package.planner, baseline, rows[0], snapshot)
    return {"file": bpy.data.filepath, "fiber": fiber.id, "anchors": [list(row.point) for row in anchors],
            "baseline": _metrics(state.points), "stored": _metrics(stored),
            "stored_valid": bool(p5._validate(stored, request, package.planner, snapshot).valid),
            "owner": _owner(state), "collision_radius": request.collision_policy.collision_radius,
            "request": benchmark._request_rows(request, package.planner), "visual": visual,
            "rows": rows, "top": rows[:12]}


def main():
    benchmark.base._ensure_addon(); args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_GLOBAL_PIN " + json.dumps({"fiber": record["fiber"], "baseline": record["baseline"], "top": record["top"][:3]}), flush=True)


if __name__ == "__main__":
    main()
