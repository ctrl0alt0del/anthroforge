"""Read-only audit for authored owner contact and strict Fiber crossings."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

import bpy
from mathutils import Vector


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import anthroforge
    anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), load_ui=False)
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    handler = register_fiber_sync().on_depsgraph_update
    if handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handler)


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root"))


def _proxy(scene, root, fiber):
    return next(obj for obj in scene.objects if obj.get("af_fiber_proxy") and
                not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name and
                str(obj.get("af_fiber_id")) == str(fiber.id))


def _points(scene, root, fiber):
    proxy, values = _proxy(scene, root, fiber), []
    for spline in proxy.data.splines:
        source = spline.bezier_points if spline.type == "BEZIER" else spline.points
        values.extend(proxy.matrix_world @ (point.co if spline.type == "BEZIER" else point.co.xyz)
                      for point in source)
    return [Vector(point) for point in values]


def _contact_params(solver, fiber, anchors, points):
    params = solver._runtime_params(fiber, True)
    params["segment_collisions"] = True
    targets = solver._anchor_pin_targets(points, anchors, len(points))
    params["pin_owners"] = solver._pin_owners(anchors, targets)
    return params, targets


def _strict_params(params):
    return dict(params, pin_owners={}, endpoint_owners=("", ""),
                _collision_context={"colliders": {}, "hits": {}, "pen": {}, "zones": {}, "clear": {}})


def _crossings(points, oracle, collider):
    return sum(bool(oracle.segment_hit_samples(a, b, (collider,)))
               for a, b in zip(points[:-1], points[1:]))


def _audit_persisted(solver, fiber, anchors, oracle, points):
    params, targets = _contact_params(solver, fiber, anchors, points)
    active = solver._active_colliders(oracle, points, params["margin"])
    owner = str(anchors[1].owner_id or "") if len(anchors) > 2 else ""
    collider = oracle.collider_by_id(owner)
    return {"points": len(points), "pin_indices": sorted(targets),
            "owner_zones": solver._owner_zone_limits(points, oracle, active, params),
            "owner_residual": solver._final_residual(points, oracle, params),
            "strict_residual": solver._final_residual(points, oracle, _strict_params(params)),
            "touch_owner": owner, "strict_touch_crossings": _crossings(points, oracle, collider)}


def _fresh_solve(solver, root, scene, depsgraph, fiber):
    from anthroforge.core.vcp.runtime_state import fiber_eps_pen, fiber_recompute_status
    from anthroforge.core.visualization.fiber_sync_runtime import _sync_commit_allowed
    solver.clear_cache(fiber.id)
    started = perf_counter()
    points = solver.solve_points(root, fiber, scene, depsgraph, bake=True)
    return {"points_returned": len(points), "wall_ms": (perf_counter() - started) * 1000.0,
            "reported_pen": fiber_eps_pen(fiber), "status": fiber_recompute_status(fiber),
            "commit_allowed": _sync_commit_allowed(fiber, points)}


def _audit_fiber(root, scene, depsgraph, fiber):
    from anthroforge.core.vcp.fiber_collision import CollisionOracle
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    solver = FiberSolver()
    _runtime, anchors, issue = solver._open_anchors(root, scene, depsgraph, fiber)
    oracle = CollisionOracle(root, scene, depsgraph, solver._collision_radius(fiber), solver.surface_offset)
    persisted = {} if issue else _audit_persisted(solver, fiber, anchors, oracle, _points(scene, root, fiber))
    return {"fiber": fiber.id, "issue": issue, "persisted": persisted,
            "fresh_final": {} if issue else _fresh_solve(solver, root, scene, depsgraph, fiber)}


def main():
    args = _args(); before = _hash(args.blend); _load(args.blend)
    scene, depsgraph = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    root = _root(scene)
    rows = [_audit_fiber(root, scene, depsgraph, fiber) for fiber in root.af_vcp_system.fibers]
    result = {"blend": str(Path(args.blend).resolve()), "hash_before": before,
              "hash_after": _hash(args.blend), "rows": rows}
    print("AF_OWNER_CONTACT_JSON=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
