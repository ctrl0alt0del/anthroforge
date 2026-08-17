"""Benchmark V2.3 cold capture and shared-world behavior on a loaded blend."""

import json
from pathlib import Path
from statistics import median
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (V2ColliderSnapshot, build_triangle_snapshot,
    clear_native_collision_world_cache, clear_structural_cache,
    clear_triangle_snapshot_cache, clear_v22_route_cache, clear_v23_route_cache,
    solve_v22, solve_v23)
from anthroforge.tools import fiber_v22_benchmark as v22
from anthroforge.tools import fiber_v21_benchmark as v21
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as common


def _capture_array(obj, index, depsgraph):
    vertices, triangles = common._surface(obj, depsgraph)
    if not len(vertices) or not len(triangles): return None, 0.0
    owner = str(obj.get("af_scp_id", "") or ""); generation, elapsed = v22._generation(vertices, triangles, index)
    return V2ColliderSnapshot(f"{owner}:{index}", owner, vertices, triangles, generation), elapsed


def _array_colliders(scene, root, depsgraph):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    rows, elapsed = [], 0.0
    for index, obj in enumerate(iter_geometry_mesh_scp_objects(scene, root.name)):
        row, cost = _capture_array(obj, index, depsgraph); elapsed += cost
        if row is not None: rows.append(row)
    return tuple(rows), elapsed


def _capture(root, fiber, depsgraph, builder):
    started = perf_counter(); colliders, digest_ms = builder(bpy.context.scene, root, depsgraph)
    anchors, _legacy = common._open_anchors(root, fiber, depsgraph)
    request = common._request(root, fiber, anchors, colliders)
    return request, _ms(started), digest_ms


def _clear(version):
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache(); clear_structural_cache()
    clear_v22_route_cache() if version == "v22" else clear_v23_route_cache()


def _measure_cold(solver, request, version, repeats):
    rows = []
    for _index in range(max(1, repeats)):
        _clear(version); started = perf_counter(); result = solver(request)
        rows.append((_ms(started), result))
    return _summary(rows)


def _measure_warm(solver, request, version, repeats):
    _clear(version); solver(request); rows = []
    for _index in range(max(1, repeats)):
        started = perf_counter(); result = solver(request); rows.append((_ms(started), result))
    return _summary(rows)


def _summary(rows):
    times = [row[0] for row in rows]; result = rows[-1][1]
    return {"median_ms": median(times), "min_ms": min(times), "max_ms": max(times),
            "result": _result(result), "trace": vars(result.trace)}


def _result(value):
    result = value.result
    return {"termination": result.termination.value, "validated": result.validated,
            "route": result.route_branch, "points": result.points, "message": result.message}


def _v1(root, fiber, depsgraph):
    started = perf_counter(); points = v21.p5._v1_solve(root, fiber, depsgraph)
    return {"ms": _ms(started), "points": tuple(tuple(value) for value in points)}


def _visual(v1_result, v22_result, v23_result, snapshot):
    rows = tuple(np.asarray(value) for value in (v1_result["points"],
                 v22_result["result"]["points"], v23_result["result"]["points"]))
    return {"v1": rows[0].tolist(), "v22": rows[1].tolist(), "v23": rows[2].tolist(),
            "nearby_triangles": p41._nearby_faces(snapshot, rows).tolist()}


def _record(args):
    root = common._root(); fiber = common._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); v1_result = _v1(root, fiber, depsgraph)
    old, old_capture, old_digest = _capture(root, fiber, depsgraph, v22._colliders)
    new, new_capture, new_digest = _capture(root, fiber, depsgraph, _array_colliders)
    old_cold = _measure_cold(solve_v22, old, "v22", args.repeats)
    new_cold = _measure_cold(solve_v23, new, "v23", args.repeats)
    old_warm = _measure_warm(solve_v22, old, "v22", args.repeats)
    new_warm = _measure_warm(solve_v23, new, "v23", args.repeats)
    snapshot = build_triangle_snapshot(new.colliders)
    return _payload(args, v1_result, (old_capture, old_digest, old_cold, old_warm),
                    (new_capture, new_digest, new_cold, new_warm), snapshot)


def _payload(args, v1_result, old, new, snapshot):
    delta = _delta(old[2]["result"]["points"], new[2]["result"]["points"])
    return {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
            "fiber": args.fiber_id, "v1": v1_result,
            "v22": {"capture_ms": old[0], "digest_ms": old[1], "cold": old[2], "warm": old[3]},
            "v23": {"capture_ms": new[0], "digest_ms": new[1], "cold": new[2], "warm": new[3]},
            "max_v22_v23_delta": delta, "visual": _visual(v1_result, old[2], new[2], snapshot)}


def _delta(first, second):
    a, b = np.asarray(first), np.asarray(second)
    return float(np.max(np.linalg.norm(a - b, axis=1))) if a.shape == b.shape and len(a) else float("inf")


def _ms(started):
    return 1000.0 * (perf_counter() - started)


def main():
    args = v21._arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V23", json.dumps({"fiber": record["fiber"], "v22_capture": record["v22"]["capture_ms"],
          "v23_capture": record["v23"]["capture_ms"], "v22_cold": record["v22"]["cold"]["median_ms"],
          "v23_cold": record["v23"]["cold"]["median_ms"], "delta": record["max_v22_v23_delta"]}), flush=True)


if __name__ == "__main__":
    main()
