"""Identify production Fibers whose V2.4 planner uses the lifted-bridge branch."""

import argparse
import json
from pathlib import Path
import sys

import bpy

from anthroforge.core.vcp.v2 import (build_triangle_snapshot_known,
    cached_native_collision_world_batch, solve_v24, v22_snapshot_key)
from anthroforge.core.vcp.v2 import planner as planner_impl
from anthroforge.tools import fiber_v24_benchmark as v24
from anthroforge.tools import fiber_v2_planner_benchmark as common


_EVENTS = []
_FIBER = ""
_ROUTE_TAGS = {}


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"):
        return
    import anthroforge
    anthroforge.register()


def _bridge_event(start, end, factor, route):
    return {"fiber": _FIBER, "branch": "BRIDGE", "factor": float(factor),
            "owner": str(start.owner_id or ""), "start": list(start.point),
            "end": list(end.point), "points": [list(row) for row in route]}


def _local_bridge(state, start, end, first_normal, last_normal):
    for factor in planner_impl._SURFACE_FACTORS:
        for sign in (1.0, -1.0):
            route = planner_impl._bridge_points(state, start.point, end.point,
                                                first_normal, last_normal, factor * sign)
            if planner_impl._route_clear(state, route, start.owner_id, end.owner_id):
                value = planner_impl._shortcut_route(state, route, start.owner_id, end.owner_id)
                _EVENTS.append(_bridge_event(start, end, factor * sign, value)); return value
    return None


def _mesh_path(original, state, points, faces, start, goal):
    value = original(state, points, faces, start, goal)
    _EVENTS.append({"fiber": _FIBER, "branch": "MESH", "vertices": len(value)})
    return value


def _surface_on(original, state, collider, start, end):
    before = len(_EVENTS); value = original(state, collider, start, end)
    created = _EVENTS[before:]; branch = _created_branch(created, value)
    if value is not None:
        _ROUTE_TAGS[id(value)] = branch
    return value


def _created_branch(events, value):
    if value is None:
        return {"branch": "FAILED"}
    bridges = [row for row in events if row["branch"] == "BRIDGE"]
    return ({"branch": "BRIDGE", "factor": bridges[-1]["factor"]} if bridges
            else {"branch": "MESH"})


def _surface_route(original, state, start, end):
    value = original(state, start, end); tag = _ROUTE_TAGS.get(id(value), {"branch": "FAILED"})
    event = {"fiber": _FIBER, "branch": "SELECTED", "selected": tag["branch"],
             "owner": str(start.owner_id or ""), "start": list(start.point), "end": list(end.point)}
    if "factor" in tag:
        event["factor"] = tag["factor"]
    _EVENTS.append(event); return value


def _capture(root, depsgraph):
    colliders, _elapsed = v24._native_colliders(bpy.context.scene, root, depsgraph)
    sample = _request(root, root.af_vcp_system.fibers[0], depsgraph, colliders)
    world = cached_native_collision_world_batch(colliders, v22_snapshot_key(sample))
    return colliders, world, build_triangle_snapshot_known(colliders, world.closed_flags)


def _request(root, fiber, depsgraph, colliders):
    anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
    return common._request(root, fiber, anchors, colliders)


def _solve(root, fiber, depsgraph, colliders, snapshot):
    global _FIBER
    _FIBER = fiber.id; package = solve_v24(_request(root, fiber, depsgraph, colliders), snapshot)
    events = [row for row in _EVENTS if row["fiber"] == fiber.id]
    return {"fiber": fiber.id, "mode": package.planner.mode.value,
            "termination": package.result.termination.value, "events": events}


def _solve_safe(root, fiber, depsgraph, colliders, snapshot):
    try:
        return _solve(root, fiber, depsgraph, colliders, snapshot)
    except (RuntimeError, ValueError) as error:
        return {"fiber": fiber.id, "mode": "", "termination": "ERROR",
                "events": [], "error": str(error)}


def _record():
    root = common._root(); depsgraph = bpy.context.evaluated_depsgraph_get()
    colliders, _world, snapshot = _capture(root, depsgraph)
    mesh = planner_impl._surface_mesh_path; surface = planner_impl._surface_on_collider
    route = planner_impl._surface_route; planner_impl._local_surface_bridge = _local_bridge
    planner_impl._surface_mesh_path = lambda *args: _mesh_path(mesh, *args)
    planner_impl._surface_on_collider = lambda *args: _surface_on(surface, *args)
    planner_impl._surface_route = lambda *args: _surface_route(route, *args)
    rows = [_solve_safe(root, fiber, depsgraph, colliders, snapshot)
            for fiber in root.af_vcp_system.fibers]
    return {"file": bpy.data.filepath, "fibers": rows}


def main():
    _ensure_addon(); args = _args(); record = _record(); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    hits = [row["fiber"] for row in record["fibers"]
            if any(event["branch"] == "BRIDGE" for event in row["events"])]
    print("AF_V25_BRANCH2 " + json.dumps({"hits": hits}), flush=True)


if __name__ == "__main__":
    main()
