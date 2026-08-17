"""Benchmark the V2.4 native batch cold path against V1 and V2.3."""

import json
from pathlib import Path
from statistics import median
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (V2ArrayColliderSnapshot, build_triangle_snapshot_known,
    cached_native_collision_world_batch, clear_native_collision_world_cache,
    clear_structural_cache, clear_triangle_snapshot_cache, clear_v23_route_cache,
    clear_v24_route_cache, solve_v23, solve_v24, v22_snapshot_key)
from anthroforge.tools import fiber_v23_benchmark as v23
from anthroforge.tools import fiber_v22_benchmark as v22
from anthroforge.tools import fiber_v21_benchmark as v21
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _capture_native(obj, index, depsgraph):
    vertices, triangles = common._surface(obj, depsgraph)
    if not len(vertices) or not len(triangles): return None, 0.0
    owner = str(obj.get("af_scp_id", "") or ""); generation, elapsed = v22._generation(vertices, triangles, index)
    return V2ArrayColliderSnapshot(f"{owner}:{index}", owner, vertices, triangles, generation), elapsed


def _native_colliders(scene, root, depsgraph):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    rows, elapsed = [], 0.0
    for index, obj in enumerate(iter_geometry_mesh_scp_objects(scene, root.name)):
        row, cost = _capture_native(obj, index, depsgraph); elapsed += cost
        if row is not None: rows.append(row)
    return tuple(rows), elapsed


def _clear(version):
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache(); clear_structural_cache()
    clear_v23_route_cache() if version.startswith("v23") else clear_v24_route_cache()


def _measure(solver, request, version, repeats, warm):
    _clear(version)
    if warm: solver(request)
    rows = []
    for _index in range(max(1, repeats)):
        if not warm: _clear(version)
        started = perf_counter(); result = solver(request); rows.append((_ms(started), result))
    return _summary(rows)


def _summary(rows):
    times = [row[0] for row in rows]; value = rows[-1][1]
    return {"median_ms": median(times), "min_ms": min(times), "max_ms": max(times),
            "result": v23._result(value), "trace": vars(value.trace)}


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); legacy = v23._v1(root, fiber, depsgraph)
    old, old_capture, old_digest = v23._capture(root, fiber, depsgraph, v23._array_colliders)
    native, native_capture, native_digest = v23._capture(root, fiber, depsgraph, _native_colliders)
    old_rows = _solver_rows(solve_v23, old, "v23", args.repeats)
    array_rows = _solver_rows(solve_v23, native, "v23_array", args.repeats)
    native_rows = _solver_rows(solve_v24, native, "v24", args.repeats)
    world = cached_native_collision_world_batch(native.colliders, v22_snapshot_key(native))
    snapshot = build_triangle_snapshot_known(native.colliders, world.closed_flags)
    return _payload(args, legacy, (old_capture, old_digest, old_rows),
                    (native_capture, native_digest, array_rows),
                    (native_capture, native_digest, native_rows), snapshot)


def _solver_rows(solver, request, version, repeats):
    return (_measure(solver, request, version, repeats, False),
            _measure(solver, request, version, repeats, True))


def _payload(args, legacy, old, array, native, snapshot):
    delta = v23._delta(old[2][0]["result"]["points"], native[2][0]["result"]["points"])
    visual = _visual(legacy, old[2][0], native[2][0], snapshot)
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
            "fiber": args.fiber_id, "v1": legacy,
            "v23": _version_payload(old), "v23_array": _version_payload(array),
            "v24": _version_payload(native),
            "max_v23_v24_delta": delta, "visual": visual}


def _version_payload(rows):
    return {"capture_ms": rows[0], "digest_ms": rows[1],
            "cold": rows[2][0], "warm": rows[2][1]}


def _visual(legacy, old, native, snapshot):
    rows = tuple(np.asarray(value) for value in
                 (legacy["points"], old["result"]["points"], native["result"]["points"]))
    return {"v1": rows[0].tolist(), "v23": rows[1].tolist(), "v24": rows[2].tolist(),
            "nearby_triangles": p41._nearby_faces(snapshot, rows).tolist()}


def _ms(started):
    return 1000.0 * (perf_counter() - started)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"):
        return
    import anthroforge
    anthroforge.register()


def main():
    _ensure_addon(); args = v21._arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V24", json.dumps({"fiber": record["fiber"],
          "v23_cold": record["v23"]["cold"]["median_ms"],
          "v24_cold": record["v24"]["cold"]["median_ms"],
          "delta": record["max_v23_v24_delta"]}), flush=True)


if __name__ == "__main__":
    main()
