"""Sweep a branch-2 tangential coordinator on one fixed production route."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from anthroforge.core.vcp.v2 import solve_v24
from anthroforge.core.vcp.v2 import solver as solver_impl
from anthroforge.core.vcp.v2 import solver_v23 as v23
from anthroforge.tools import fiber_v25_branch2_sweep as base


def _configs():
    for trust in (0.40, 0.60, 1.0):
        for offset in (2.5, 3.0, 4.0):
            for length in (0.10, 0.30, 0.90, 1.80, 3.60):
                for curvature in (0.0, 0.005, 0.02, 0.10):
                    yield trust, offset, 0.01, length, curvature


def _tangent_candidate(state, trust, offset):
    owner = solver_impl._surface_owner(state.request)
    colliders = solver_impl._owner_colliders(state.request, owner)
    if not owner or not colliders:
        return state.structural.copy()
    closest, normals, distances, _ids, contained = solver_impl._collision_world(state, colliders).nearest(state.points)
    directions = solver_impl._contact_directions(state.points, closest, normals, distances, contained)
    output = _tangent_step(state, directions, distances, trust, offset)
    solver_impl._restore_pins(output, state.pins); return output


def _tangent_step(state, directions, distances, trust, offset):
    delta = np.asarray(state.structural) - state.points
    normal = np.sum(delta * directions, axis=1)[:, None]
    tangent = delta - normal * directions
    radius = state.request.collision_policy.collision_radius
    shell = (float(offset) * radius - np.asarray(distances))[:, None] * directions
    return np.asarray(state.points) + float(trust) * (tangent + shell)


def _request_with(request, config):
    _trust, _offset, proximal, length, curvature = config
    settings = replace(request.settings, length_weight=length, curvature_weight=curvature)
    return replace(request, settings=settings), proximal


def _row(config, samples, package):
    value = base._row(config[2:], samples, package)
    value.update({"trust": config[0], "shell_factor": config[1], "mode": "TANGENT_SHELL"})
    return value


def _measure(request, snapshot, config, repeats=3):
    configured, proximal = _request_with(request, config); solver_impl.PROXIMAL_WEIGHT = proximal
    solver_impl._surface_candidate = lambda state: _tangent_candidate(state, config[0], config[1])
    samples = [_timed(configured, snapshot) for _index in range(repeats)]
    return _row(config, [row[0] for row in samples], samples[-1][1])


def _timed(request, snapshot):
    from time import perf_counter
    started = perf_counter(); package = solve_v24(request, snapshot)
    return 1000.0 * (perf_counter() - started), package


def _sweep(request, snapshot, planner):
    original = v23._planner, solver_impl.PROXIMAL_WEIGHT, solver_impl._surface_candidate
    v23._planner = lambda *_args, **_kwargs: (planner, (True, True, 0.0, 0), (True, False, False))
    try:
        return sorted((_measure(request, snapshot, row) for row in _configs()), key=base._rank)
    finally:
        v23._planner, solver_impl.PROXIMAL_WEIGHT, solver_impl._surface_candidate = original


def _record(args):
    root = base.common._root(); fiber = base.common._fiber(root, args.fiber_id)
    request, snapshot, anchors = base._capture(root, fiber, base.bpy.context.evaluated_depsgraph_get())
    baseline = solve_v24(request, snapshot); rows = _sweep(request, snapshot, baseline.planner)
    return {"file": base.bpy.data.filepath, "file_sha256": base.common._file_hash(base.bpy.data.filepath),
            "fiber": fiber.id, "anchors": [list(row.point) for row in anchors],
            "planner_metrics": base._metrics(baseline.planner.reference), "baseline": base._baseline(baseline),
            "best": rows[0], "top": rows[:8], "rows": rows,
            "visual": base._visual(root, fiber, baseline.planner, baseline, rows[0], snapshot)}


def main():
    base._ensure_addon(); args = base._args(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V25_BRANCH2_CONTROLLER " + json.dumps({"fiber": record["fiber"],
          "best": record["best"]}, default=str), flush=True)


if __name__ == "__main__":
    main()
