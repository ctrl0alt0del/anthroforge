"""Benchmark Fiber V2.2 identity, preview, and fresh-final policies."""

from dataclasses import replace
from hashlib import blake2b
import json
from pathlib import Path
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot, clear_native_collision_world_cache,
    clear_structural_cache, clear_triangle_snapshot_cache, clear_v21_route_cache,
    clear_v22_route_cache, solve_package61, solve_v21, solve_v22,
    triangle_snapshot_cache_stats, v22_request_signature, V2ColliderSnapshot)
from anthroforge.tools import fiber_v21_benchmark as v21b
from anthroforge.tools import fiber_v2_planner_41_benchmark as p41
from anthroforge.tools import fiber_v2_planner_benchmark as bench


def _generation(vertices, triangles, index):
    started = perf_counter(); digest = blake2b(digest_size=16)
    digest.update(np.asarray(vertices, dtype=np.float64).tobytes())
    digest.update(np.asarray(triangles, dtype=np.int64).tobytes())
    return ("v22", str(index), digest.hexdigest()), 1000.0 * (perf_counter() - started)


def _capture_collider(obj, index, depsgraph):
    vertices, triangles = bench._surface(obj, depsgraph)
    if not len(vertices) or not len(triangles):
        return None, 0.0
    owner = str(obj.get("af_scp_id", "") or ""); generation, elapsed = _generation(vertices, triangles, index)
    row = V2ColliderSnapshot(f"{owner}:{index}", owner, tuple(map(tuple, vertices)),
                             tuple(map(tuple, triangles)), generation)
    return row, elapsed


def _colliders(scene, root, depsgraph):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    rows, elapsed = [], 0.0
    for index, obj in enumerate(iter_geometry_mesh_scp_objects(scene, root.name)):
        row, cost = _capture_collider(obj, index, depsgraph); elapsed += cost
        if row is not None:
            rows.append(row)
    return tuple(rows), elapsed


def _clear_v22(routes=True):
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache(); clear_structural_cache()
    if routes:
        clear_v22_route_cache()


def _measure_v22(call, request, repeats, signature=v22_request_signature):
    rows = [call(request, index) for index in range(max(1, repeats))]
    signatures = [v21b._once(lambda row=row: signature(row))[0] for row in rows]
    times, results = [], []
    for row in rows:
        elapsed, result = v21b._once(lambda row=row: solve_v22(row)); times.append(elapsed); results.append(result)
    return v21b._summary(times), results, v21b._summary(signatures)


def _measure_v22_preview(request, repeats):
    rows = [v21b._handle_variant(request, index) for index in range(max(1, repeats))]
    times, results = [], []
    for row in rows:
        elapsed, result = v21b._once(lambda row=row: solve_v22(row, preview=True))
        times.append(elapsed); results.append(result)
    return v21b._summary(times), results


def _measure_v22_final(request, repeats):
    rows = [v21b._handle_variant(request, index) for index in range(max(1, repeats))]
    times, results = [], []
    for row in rows:
        solve_v22(row, preview=True); elapsed, result = v21b._once(lambda row=row: solve_v22(row))
        times.append(elapsed); results.append(result)
    return v21b._summary(times), results


def _baseline(root, fiber, depsgraph, request, snapshot, repeats):
    v1 = v21b._measure(lambda: v21b.p5._v1_solve(root, fiber, depsgraph), repeats)
    v21b._clear_v2(); p61 = v21b._measure(lambda: solve_package61(request, snapshot), repeats)
    clear_v21_route_cache(); solve_v21(request, snapshot)
    old = v21b._measure(lambda: solve_v21(request, snapshot), repeats)
    _clear_v22(); cold = v21b._once(lambda: solve_v22(request)); warm = v21b._measure(lambda: solve_v22(request), repeats)
    return v1, p61, old, cold, warm


def _properties(request, snapshot, repeats):
    p61 = v21b._variant_measure(solve_package61, request, snapshot, repeats)
    solve_v21(request, snapshot); old = v21b._variant_measure(solve_v21, request, snapshot, repeats)
    solve_v22(request); new = _measure_v22(v21b._variant, request, repeats)
    return p61, old, new


def _handles(request, snapshot, repeats):
    p61 = v21b._handle_measure(solve_package61, request, snapshot, repeats)
    clear_v21_route_cache(); solve_v21(request, snapshot)
    old = v21b._handle_measure(solve_v21, request, snapshot, repeats)
    clear_v22_route_cache(); solve_v22(request); preview = _measure_v22_preview(request, repeats)
    clear_v22_route_cache(); solve_v22(request); final = _measure_v22_final(request, repeats)
    return p61, old, preview, final


def _solver_payload(measured, request, snapshot):
    return v21b._solver_payload(measured[0], measured[1], request, snapshot)


def _edit_payload(measured, request, snapshot):
    payload = _solver_payload(measured, request, snapshot)
    if len(measured) > 2:
        payload["request_signature_timing"] = measured[2]
    return payload


def _visual(request, baseline, snapshot):
    v1, p61, old, _cold, new = baseline
    routes = (np.asarray(v1[1][-1]), np.asarray(p61[1][-1].result.points),
              np.asarray(old[1][-1].result.points), np.asarray(new[1][-1].result.points))
    result = {key: row.tolist() for key, row in zip(("v1", "package61", "v21", "v22"), routes)}
    result["nearby_triangles"] = p41._nearby_faces(snapshot, routes).tolist(); return result


def _handle_visual(handles, snapshot):
    p61, old, preview, final = handles
    rows = tuple(np.asarray(item) for item in (p61[1][-1].result.points, old[1][-1].result.points,
                                               preview[1][-1].result.points, final[1][-1].result.points))
    result = {key: row.tolist() for key, row in zip(("package61", "v21", "v22_preview", "v22_final"), rows)}
    result["nearby_triangles"] = p41._nearby_faces(snapshot, rows).tolist(); return result


def _payload(root, fiber, request, snapshot, timing, rows):
    baseline, properties, handles = rows; v1, p61, old, cold, new = baseline
    prop61, prop21, prop22 = properties; handle61, handle21, preview, final = handles
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "fiber_id": fiber.id, "triangles": len(snapshot.triangles), "colliders": snapshot.source_count,
            "capture_ms": timing[0], "generation_ms": timing[1], "v1": v21b._v1_payload(v1[0], v1[1][-1], request, snapshot),
            "package61": _solver_payload(p61, request, snapshot), "v21": _solver_payload(old, request, snapshot),
            "v22_cold_ms": cold[0], "v22": _solver_payload(new, request, snapshot),
            "package61_edit": _edit_payload(prop61, request, snapshot), "v21_edit": _edit_payload(prop21, request, snapshot),
            "v22_edit": _edit_payload(prop22, request, snapshot), "package61_handle": _edit_payload(handle61, request, snapshot),
            "v21_handle": _edit_payload(handle21, request, snapshot), "v22_preview": _edit_payload(preview, request, snapshot),
            "v22_final": _edit_payload(final, request, snapshot), "snapshot_cache": triangle_snapshot_cache_stats(),
            "deltas": _deltas(rows), "visual": _visual(request, baseline, snapshot),
            "visual_handle": _handle_visual(handles, snapshot)}


def _deltas(rows):
    baseline, properties, handles = rows; _v1, p61, old, _cold, new = baseline
    prop61, _prop21, prop22 = properties; handle61, _handle21, preview, final = handles
    return {"p61_v22": v21b._delta(p61[1][-1], new[1][-1]),
            "v21_v22": v21b._delta(old[1][-1], new[1][-1]),
            "property_p61_v22": v21b._delta(prop61[1][-1], prop22[1][-1]),
            "preview_p61_v22": v21b._delta(handle61[1][-1], preview[1][-1]),
            "final_p61_v22": v21b._delta(handle61[1][-1], final[1][-1])}


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id); depsgraph = bpy.context.evaluated_depsgraph_get()
    started = perf_counter(); colliders, generation_ms = _colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders); anchors, _legacy = bench._open_anchors(root, fiber, depsgraph)
    request = bench._request(root, fiber, anchors, colliders); capture = 1000.0 * (perf_counter() - started)
    rows = (_baseline(root, fiber, depsgraph, request, snapshot, args.repeats),
            _properties(request, snapshot, args.repeats), _handles(request, snapshot, args.repeats))
    return _payload(root, fiber, request, snapshot, (capture, generation_ms), rows)


def main():
    args = v21b._arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    keys = ("v1", "package61", "v21", "v22", "v22_edit", "v22_preview", "v22_final")
    print("AF_V22", json.dumps({key: record[key]["timing"] for key in keys}), flush=True)


if __name__ == "__main__":
    main()
