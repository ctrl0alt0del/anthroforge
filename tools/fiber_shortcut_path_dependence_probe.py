"""Read-only real-file probe for shortcut path-dependent Fiber mutation."""

import argparse
from hashlib import sha256
import json
import sys
from time import perf_counter

import bpy


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--file", required=True)
    parser.add_argument("--shortcut", default="Cranium Lobe Width")
    parser.add_argument("--values", required=True); parser.add_argument("--drain-each", action="store_true")
    parser.add_argument("--fibers", default="FIBER_1,FIBER_2,FIBER_3,FIBER_4,FIBER_18")
    parser.add_argument("--disable-auto-repair", action="store_true")
    parser.add_argument("--disable-warm-start", action="store_true")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _register():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"): anthroforge.register()


def _root():
    from anthroforge.core.utils import get_af_root
    return get_af_root(bpy.context.scene)


def _fibers(root, raw):
    wanted = {value.strip().upper() for value in raw.split(",") if value.strip()}
    return tuple(row for row in root.af_vcp_system.fibers if row.id.upper() in wanted or row.name.upper() in wanted)


def _pins(fiber):
    rows = [("A", fiber.a_parent_id, fiber.a_attach_param), ("B", fiber.b_parent_id, fiber.b_attach_param)]
    rows.extend((f"M{index}", row.parent_id, row.attach_param) for index, row in enumerate(fiber.mid_touches))
    rows.extend((f"L{index}", row.parent_id, row.attach_param) for index, row in enumerate(fiber.loop_anchors))
    return {role: (owner, _digest(raw)) for role, owner, raw in rows}


def _digest(value):
    return sha256(str(value or "").encode("utf-8")).hexdigest()[:12]


def _pin_changes(before, after):
    return tuple(role for role in sorted(set(before) | set(after)) if before.get(role) != after.get(role))


def _point_hash(scene, root, fiber):
    values = _point_rows(scene, root, fiber)
    return _digest(values)


def _point_rows(scene, root, fiber):
    from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
    points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    return tuple(tuple(float(value) for value in point) for point in points)


def _max_delta(first, second):
    if len(first) != len(second): return float("inf")
    return max((sum((a - b) ** 2 for a, b in zip(left, right)) ** 0.5
                for left, right in zip(first, second)), default=0.0)


def _preflight(root, scene, fiber):
    from anthroforge.core.vcp.fiber_anchor_preflight import anchor_preflight_summary
    from anthroforge.core.visualization.fiber_refinement import _hard_anchor_preflight
    result = _hard_anchor_preflight(root, scene, fiber, "FINAL")
    return {"valid": result is None or result.valid,
            "summary": "" if result is None or result.valid else anchor_preflight_summary(result)}


def _fiber_state(root, scene, fiber):
    from anthroforge.core.vcp.runtime_state import fiber_recompute_status
    return {"pins": _pins(fiber), "points": _point_hash(scene, root, fiber),
            "preflight": _preflight(root, scene, fiber), "status": fiber_recompute_status(fiber)}


def _states(root, scene, fibers):
    return {fiber.id: _fiber_state(root, scene, fiber) for fiber in fibers}


def _event(row, value, root, scene, fibers, drain):
    from anthroforge.core.visualization import fiber_refinement
    before = {fiber.id: _pins(fiber) for fiber in fibers}; started = perf_counter(); row.proxy_float = value
    setter_ms = (perf_counter() - started) * 1000.0; jobs = tuple(sorted(job.fiber_id for job in fiber_refinement._JOBS.values()))
    drained = fiber_refinement.drain_fiber_refinements() if drain else None
    changes = {fiber.id: _pin_changes(before[fiber.id], _pins(fiber)) for fiber in fibers}
    hashes = {fiber.id: _point_hash(scene, root, fiber) for fiber in fibers}
    return {"value": value, "setter_ms": setter_ms, "jobs": jobs, "drained": drained,
            "pin_changes": changes, "point_hashes": hashes}


def _run(args, root, scene, fibers, row):
    from anthroforge.core.visualization import fiber_refinement
    events = []
    for phase, values in enumerate(_phases(args.values)):
        events.extend(dict(_event(row, value, root, scene, fibers, args.drain_each), phase=phase)
                      for value in values)
        if not args.drain_each:
            fiber_refinement.drain_fiber_refinements(); events[-1]["phase_drained"] = True
    return events, True


def _configure(args, root):
    from anthroforge.core.visualization import fiber_refinement
    if args.disable_auto_repair:
        fiber_refinement._repair_current_preflight = lambda _root, _scene, _fiber, result: result
    if args.disable_warm_start:
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        with suppress_vcp_prop_updates():
            for fiber in root.af_vcp_system.fibers: fiber.use_warm_start = False


def _phases(raw):
    return tuple(tuple(float(value.strip()) for value in phase.split(",") if value.strip())
                 for phase in raw.split(";") if phase.strip())


def main():
    args = _args(); _register(); bpy.ops.wm.open_mainfile(filepath=args.file)
    root, scene = _root(), bpy.context.scene; _configure(args, root); fibers = _fibers(root, args.fibers)
    row = next(item for item in root.af_shortcut_system.shortcuts if item.name == args.shortcut)
    initial = _states(root, scene, fibers)
    initial_points = {fiber.id: _point_rows(scene, root, fiber) for fiber in fibers}
    events, drained = _run(args, root, scene, fibers, row)
    round_trip = {fiber.id: _max_delta(initial_points[fiber.id], _point_rows(scene, root, fiber))
                  for fiber in fibers}
    result = {"initial": initial, "events": events, "drained": drained,
              "final_value": float(row.proxy_float), "final": _states(root, scene, fibers),
              "round_trip_max_delta": round_trip}
    print("AF_SHORTCUT_PATH", json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
