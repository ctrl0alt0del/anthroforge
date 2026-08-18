"""Probe collision-safe tangent corrections at hard Fiber surface pins."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import solve_v24
from anthroforge.core.vcp.v2 import pin_smoothing_geometry as geometry
from anthroforge.core.vcp.v2 import solver as p5
from anthroforge.core.vcp.v2 import solver_pin_smoothing as smoothing
from anthroforge.tools import fiber_pin_smoothing_benchmark as benchmark
from anthroforge.tools import fiber_v25_branch2_sweep as base


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--fiber-id", default="FIBER_22")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _state(request, snapshot, package):
    live = SimpleNamespace(request=request, planner=package.planner, snapshot=snapshot,
                           points=np.asarray(package.result.points), pair_cache=p5.V2SweepPairCache())
    return smoothing._smoothing_state(live)


def _surface_windows(state):
    spans = tuple(state.planner.spans)
    return tuple(row for row in state.windows if _surface_adjacent(row, spans))


def _surface_adjacent(window, spans):
    edges = {window.pin - 1, window.pin}
    return any(span.branch.value == "SURFACE_BRIDGE" and
               edges.intersection(range(span.first_edge, span.first_edge + span.edge_count)) for span in spans)


def _normal(state, window):
    owner = state.request.anchors[window.anchor].owner_id; world = state.owner_worlds[owner]
    return smoothing._unit(world.nearest(state.reference[window.pin:window.pin + 1])[1][0])


def _shared(points, window, normal, mode):
    incoming = geometry._direction(points[window.pin] - points[window.left])
    outgoing = geometry._direction(points[window.right] - points[window.pin])
    source = {"average": incoming + outgoing, "incoming": incoming,
              "outgoing": outgoing, "chord": points[window.right] - points[window.left]}[mode]
    tangent = source - float(np.dot(source, normal)) * normal
    return geometry._direction(tangent)


def _raw_candidate(state, window, mode):
    points = state.reference; tangent = _shared(points, window, _normal(state, window), mode)
    output = points.copy(); output[window.left:window.pin + 1] = geometry._side(
        points, window.left, window.pin, geometry._edge_direction(points, window.left), tangent)
    output[window.pin:window.right + 1] = geometry._side(
        points, window.pin, window.right, tangent, geometry._edge_direction(points, window.right - 1))
    return output


def _move_side(reference, candidate, window, side):
    output = reference.copy()
    if side in ("both", "incoming"): output[window.left:window.pin] = candidate[window.left:window.pin]
    if side in ("both", "outgoing"): output[window.pin + 1:window.right + 1] = candidate[window.pin + 1:window.right + 1]
    return output


def _tangent_rows(state, candidate, window):
    owner = state.request.anchors[window.anchor].owner_id; world = state.owner_worlds[owner]
    indices = smoothing._movable_indices(window, state.pins); normals = world.nearest(state.reference[indices])[1]
    delta = candidate[indices] - state.reference[indices]; unit = p5._unit_rows(normals)
    candidate[indices] = state.reference[indices] + delta - np.sum(delta * unit, axis=1)[:, None] * unit
    return candidate


def _preserve_offset(state, candidate, window):
    owner = state.request.anchors[window.anchor].owner_id; world = state.owner_worlds[owner]
    indices = smoothing._movable_indices(window, state.pins); reference = state.reference[indices]
    ref_near = world.nearest(reference); near = world.nearest(candidate[indices])
    direction = p5._contact_directions(candidate[indices], *near[:3], near[4])
    candidate[indices] = near[0] + ref_near[2][:, None] * direction
    return candidate


def _candidate(state, window, mode, side, strength, projection):
    raw = _move_side(state.reference, _raw_candidate(state, window, mode), window, side)
    output = state.reference + float(strength) * (raw - state.reference)
    if projection in ("tangent", "offset"): output = _tangent_rows(state, output, window)
    if projection == "offset": output = _preserve_offset(state, output, window)
    p5._restore_pins(output, state.pins); return output


def _trial(state, window, mode, side, strength, projection):
    candidate = _candidate(state, window, mode, side, strength, projection); envelope = p5._waypoint_envelope(state.points, (candidate,))
    started = perf_counter(); step = p5._safe_step_p51(state, state.points, candidate, envelope); elapsed = p5._elapsed(started)
    fraction = p5._backed_fraction(step.safe_step) if step.valid else 0.0
    proposed = p5._interpolate(state.points, candidate, fraction); p5._restore_pins(proposed, state.pins)
    checked = p5._validate(proposed, state.request, state.planner, state.snapshot)
    return _row(window, mode, side, strength, projection, candidate, proposed, step, checked, elapsed, state)


def _row(window, mode, side, strength, projection, candidate, proposed, step, checked, elapsed, state):
    return {"pin": window.pin, "mode": mode, "side": side, "strength": strength,
            "projection": projection, "candidate": base._metrics(candidate), "accepted": base._metrics(proposed),
            "safe_step": float(step.safe_step), "valid": bool(checked.valid), "ccd_ms": elapsed,
            "pairs": int(step.candidate_pairs), "tested": int(step.tested_pairs),
            "limiter": smoothing._limiter(state), "max_displacement": _displacement(state.points, proposed),
            "points": proposed.tolist()}


def _displacement(first, second):
    return float(np.max(np.linalg.norm(np.asarray(second) - first, axis=1)))


def _trials(state):
    rows = []
    for window in _surface_windows(state):
        for mode in ("average", "incoming", "outgoing", "chord"):
            for side in ("both", "incoming", "outgoing"):
                for projection in ("pin", "tangent", "offset"):
                    for strength in (.25, .5, 1.0, 1.5): rows.append(_trial(state, window, mode, side, strength, projection))
    return rows


def _rank(row):
    return (not row["valid"], row["accepted"]["max_turn_deg"], row["accepted"]["p95_turn_deg"], row["ccd_ms"])


def _record(args):
    root = base.common._root(); fiber = base.common._fiber(root, args.fiber_id)
    request, snapshot, anchors = base._capture(root, fiber, bpy.context.evaluated_depsgraph_get())
    package = solve_v24(request, snapshot); state = _state(request, snapshot, package); rows = sorted(_trials(state), key=_rank)
    return {"file": bpy.data.filepath, "fiber": fiber.id, "anchors": [list(row.point) for row in anchors],
            "baseline": base._metrics(package.result.points), "windows": [vars(row) for row in _surface_windows(state)],
            "rows": rows, "top": rows[:20]}


def main():
    benchmark.base._ensure_addon(); args = _args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_PIN_TANGENT " + json.dumps({"fiber": record["fiber"], "baseline": record["baseline"], "top": record["top"][:3]}), flush=True)


if __name__ == "__main__":
    main()
