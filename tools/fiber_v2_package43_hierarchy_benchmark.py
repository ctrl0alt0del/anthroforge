"""Measure Package 4.3 BLAS reuse and TLAS refit on a real Blender collider set."""

import argparse
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import build_native_collision_world
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--fiber-id", default="FIBER_21"); parser.add_argument("--repeats", type=int, default=7)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _capture(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
    shortcut = next(row for row in root.af_shortcut_system.shortcuts if row.name == "Maxilla Top Radius")
    return colliders, bench._request(root, fiber, anchors, colliders), str(shortcut.owner_id)


def _matrix(offset):
    value = np.eye(4); value[0, 3] = offset
    return value


def _measure(call, repeats):
    values = []
    for index in range(repeats):
        started = perf_counter(); call(index); values.append(1000.0 * (perf_counter() - started))
    return values


def _query(world, request):
    points = np.asarray([anchor.point for anchor in request.anchors]); edges = tuple((i, i + 1) for i in range(len(points) - 1))
    owners = tuple((request.anchors[i].owner_id, request.anchors[i + 1].owner_id) for i in range(len(edges)))
    radius = request.collision_policy.collision_radius; span = max(2.5 * radius, 1.0e-7)
    return world.validate(points, edges, owners, span, radius - request.tolerances.clearance_slack)


def _record(args):
    colliders, request, owner = _capture(args); identity = (None,) * len(colliders); target = _target(colliders, owner)
    started = perf_counter(); world = build_native_collision_world(colliders); build_ms = 1000.0 * (perf_counter() - started)
    refits = _measure(lambda index: world.update_transform(target, _matrix(.001 if index % 2 else 0.0)), args.repeats)
    transforms = list(identity); transforms[target] = _matrix(.001)
    rebuilds = _measure(lambda _index: build_native_collision_world(colliders, transforms), args.repeats)
    world.update_transform(target, transforms[target]); clean = build_native_collision_world(colliders, transforms)
    return _payload(colliders, request, target, build_ms, refits, rebuilds, _query(world, request), _query(clean, request))


def _target(colliders, owner):
    return next((index for index, item in enumerate(colliders) if item.owner_id == owner), 0)


def _summary(values):
    return {"median_ms": statistics.median(values), "min_ms": min(values), "max_ms": max(values)}


def _payload(colliders, request, target, build_ms, refits, rebuilds, refit, clean):
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "colliders": len(colliders), "triangles": sum(len(item.triangles) for item in colliders),
            "target_index": target, "target_id": colliders[target].collider_id,
            "target_owner": colliders[target].owner_id, "cold_build_ms": build_ms,
            "transform_refit": _summary(refits), "clean_rebuild": _summary(rebuilds),
            "speedup": statistics.median(rebuilds) / statistics.median(refits),
            "query_parity": refit.clear == clean.clear and refit.blockers == clean.blockers,
            "query_clear": [bool(value) for value in refit.clear], "fiber": request.source_revision}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PACKAGE43_HIERARCHY", json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
