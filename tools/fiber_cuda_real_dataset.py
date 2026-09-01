"""Capture a read-only packed multi-Fiber contact workload from Blender."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np


def arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True); parser.add_argument("--fibers", default="")
    parser.add_argument("--shortcut", default="")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): value.update(block)
    return value.hexdigest()


def ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge; anthroforge.register()


def root_object():
    return next(obj for obj in bpy.context.scene.objects if obj.get("anthroforge_root") and hasattr(obj, "af_vcp_system"))


def selected_fibers(root, names):
    wanted = {value.strip().upper() for value in names.split(",") if value.strip()}
    rows = tuple(root.af_vcp_system.fibers)
    return tuple(row for row in rows if not wanted or row.id.upper() in wanted or row.name.upper() in wanted)


def shortcut_fiber_ids(root, name):
    from anthroforge.core.visualization import fiber_refinement
    original, found = fiber_refinement.request_fiber_refinement, []
    def record(_root, _scene, fiber, **_kwargs):
        found.append(fiber.id); return fiber_refinement.RefinementRequest(True)
    row = next((item for item in root.af_shortcut_system.shortcuts if item.name == name), None)
    if row is None: raise RuntimeError(f"Shortcut not found: {name}")
    fiber_refinement.request_fiber_refinement = record
    try: row.proxy_float = float(row.proxy_float) * 1.01
    finally: fiber_refinement.request_fiber_refinement = original
    return tuple(dict.fromkeys(found))


def workload_fibers(root, args):
    if not args.shortcut: return selected_fibers(root, args.fibers)
    affected = set(shortcut_fiber_ids(root, args.shortcut))
    return tuple(row for row in root.af_vcp_system.fibers if row.id in affected)


def capture_request(root, fiber):
    from anthroforge.core.visualization.fiber_refinement import _hard_anchor_preflight, _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request
    preflight = _hard_anchor_preflight(root, bpy.context.scene, fiber, "FINAL")
    if preflight is not None and not preflight.valid: return None, "invalid attachment"
    runtime = _prepared_session(root, bpy.context.scene, fiber, "FINAL")
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: return None, runtime.invalid_reason or runtime.runtime_error
    request = _request(runtime); runtime.cancel(); return request, ""


def reference_points(request):
    from anthroforge.core.vcp.v3.cyclic import v3_reference
    direct, _pins = v3_reference(request)
    if len(request.warm_seed) == len(direct): return np.asarray(request.warm_seed, dtype=np.float64)
    return np.asarray(direct, dtype=np.float64)


def collider_signature(request):
    return tuple((row.collider_id, row.generation, len(row.vertices), len(row.triangles)) for row in request.colliders)


def activation_padding(request):
    radius = request.collision_policy.collision_radius; slack = request.tolerances.clearance_slack
    return radius + max(4.0 * slack, 0.25 * radius)


def fiber_pairs(points, snapshot, padding):
    from anthroforge.core.vcp.v2.collision import _candidate_pairs
    edges = np.column_stack((np.arange(len(points) - 1), np.arange(1, len(points)))).astype(np.int64)
    return edges, _candidate_pairs(points, points, edges, snapshot, padding, None)


def append_fiber(storage, request, snapshot, fiber):
    points = reference_points(request); edges, pairs = fiber_pairs(points, snapshot, activation_padding(request))
    offset = sum(len(row) for row in storage[0]); segments = points[edges]
    storage[0].append(segments); storage[1].append(pairs[:, 0].astype(np.int32) + offset)
    storage[2].append(pairs[:, 1].astype(np.int32))
    return {"fiber": fiber.name, "nodes": len(points), "edges": len(edges), "pairs": len(pairs)}


def joined(rows, shape, dtype):
    return np.ascontiguousarray(np.concatenate(rows, axis=0), dtype=dtype) if rows else np.empty(shape, dtype=dtype)


def build_dataset(root, fibers):
    from anthroforge.core.vcp.v2.collision import build_triangle_snapshot
    requests, skipped = [], []
    for fiber in fibers:
        request, reason = capture_request(root, fiber)
        if request is None: skipped.append({"fiber": fiber.name, "reason": reason})
        elif request.settings.topology.value != "OPEN": skipped.append({"fiber": fiber.name, "reason": "non-open topology"})
        else: requests.append((fiber, request))
    if not requests: raise RuntimeError("No capturable open Fiber requests")
    signature = collider_signature(requests[0][1]); compatible = [(f, r) for f, r in requests if collider_signature(r) == signature]
    skipped.extend({"fiber": f.name, "reason": "different collider snapshot"} for f, r in requests if collider_signature(r) != signature)
    snapshot = build_triangle_snapshot(compatible[0][1].colliders); storage = ([], [], []); reports = []
    for fiber, request in compatible: reports.append(append_fiber(storage, request, snapshot, fiber))
    triangles = snapshot.vertices[snapshot.triangles]; data = joined(storage[0], (0, 2, 3), np.float64), triangles, joined(storage[1], (0,), np.int32), joined(storage[2], (0,), np.int32)
    return data, reports, skipped, snapshot.source_count


def save(args, data, report):
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(output, segments=data[0], triangles=data[1], segment_ids=data[2], triangle_ids=data[3])
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")


def main():
    args = arguments(); source = Path(bpy.data.filepath); before = digest(source); ensure_addon()
    root = root_object(); selected = workload_fibers(root, args)
    data, fibers, skipped, colliders = build_dataset(root, selected)
    report = {"source": str(source), "hash_before": before, "hash_after": digest(source),
              "fibers": fibers, "skipped": skipped, "colliders": colliders,
              "shortcut": args.shortcut, "requested": len(selected), "segments": len(data[0]),
              "triangles": len(data[1]), "pairs": len(data[2])}
    save(args, data, report); print(json.dumps(report)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
