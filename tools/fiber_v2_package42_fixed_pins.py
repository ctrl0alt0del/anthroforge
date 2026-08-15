"""Benchmark Package 4.1/4.2 after repairing invalid FIBER_21 hard pins in memory."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v2_package42_maxilla_benchmark as base

from anthroforge.core.vcp.v2 import V2Anchor, V2OwnerContact, plan_reference_v41, plan_reference_v42
from anthroforge.core.vcp.v2.collision import _node_rows


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True); parser.add_argument("--value", type=float, default=.2)
    parser.add_argument("--repeats", type=int, default=3); parser.add_argument("--samples", type=int, default=6)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _hash(path):
    digest = sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _triangle_samples(vertices, triangles, steps):
    rows = []
    for a, b, c in vertices[triangles]:
        for i in range(steps + 1):
            for j in range(steps + 1 - i):
                rows.append(a + (b - a) * (i / steps) + (c - a) * (j / steps))
    return np.asarray(rows, dtype=np.float64)


def _owner_candidates(request, owner, steps):
    rows = []
    for collider in request.colliders:
        if collider.owner_id == owner:
            rows.append(_triangle_samples(np.asarray(collider.vertices), np.asarray(collider.triangles), steps))
    values = np.vstack(rows)
    return np.unique(np.round(values, 12), axis=0)


def _safe_mask(points, snapshot, owner, threshold):
    contact = V2OwnerContact(owner, tuple(range(len(points))), ())
    distances, keys, _candidates, contained = _node_rows(points, snapshot, (contact,), threshold, None)
    blocked = set(contained)
    blocked.update(node for distance, (node, _face) in zip(distances, keys) if distance < threshold)
    mask = np.ones(len(points), dtype=bool); mask[list(blocked)] = False
    return mask


def _nearest_distinct(points, targets):
    chosen, rows = set(), []
    for target in targets:
        order = np.argsort(np.linalg.norm(points - target, axis=1), kind="stable")
        index = next(int(value) for value in order if int(value) not in chosen)
        chosen.add(index); rows.append(points[index])
    return np.asarray(rows)


def _repair(request, snapshot, indices, steps):
    owner = request.anchors[indices[0]].owner_id
    candidates = _owner_candidates(request, owner, steps)
    threshold = request.collision_policy.collision_radius - request.tolerances.clearance_slack
    safe = candidates[_safe_mask(candidates, snapshot, owner, threshold)]
    targets = np.asarray([request.anchors[index].point for index in indices])
    return safe, _nearest_distinct(safe, targets)


def _fixed_request(request, indices, points):
    anchors = list(request.anchors)
    for index, point in zip(indices, points):
        anchor = anchors[index]
        anchors[index] = V2Anchor(tuple(point), anchor.owner_id, anchor.role, anchor.authored_index)
    return replace(request, anchors=tuple(anchors), token=request.token + 1)


def _timed(call, repeats):
    results, times = [], []
    for _index in range(repeats):
        started = time.perf_counter(); results.append(call())
        times.append(1000.0 * (time.perf_counter() - started))
    return results[-1], times


def _row(call, repeats, request, snapshot):
    result, times = _timed(call, repeats)
    return {"median_ms": statistics.median(times), "times_ms": times,
            "termination": result.termination.value, "mode": result.mode.value,
            "message": result.message, "reference": [list(point) for point in result.reference],
            "corridor": [list(point) for point in result.corridor], "diagnostics": vars(result.diagnostics),
            "validation": base._validation(result, request, snapshot)}


def _planner_rows(request, snapshot, repeats):
    calls = (("package41", lambda: plan_reference_v41(request, snapshot)),
             ("package42", lambda: plan_reference_v42(request, snapshot)))
    return {name: _row(call, repeats, request, snapshot) for name, call in calls}


def _capture(args):
    root = base.bench._root(); fiber = base.bench._fiber(root, "FIBER_21")
    values = base._capture(args, root, fiber)
    _before, after, _passes, _update, _colliders, snapshot, request, _capture_ms, _cache = values
    return root, fiber, after, snapshot, request


def _record(args):
    source_hash = _hash(bpy.data.filepath); _root, _fiber, v1_after, snapshot, request = _capture(args)
    indices = (4, 5); safe, fixed = _repair(request, snapshot, indices, args.samples)
    updated = _fixed_request(request, indices, fixed)
    original = _planner_rows(request, snapshot, args.repeats)
    repaired = _planner_rows(updated, snapshot, args.repeats)
    return _payload(source_hash, v1_after, snapshot, request, updated, indices, safe, original, repaired)


def _payload(source_hash, v1_after, snapshot, request, updated, indices, safe, original, repaired):
    old = np.asarray([request.anchors[index].point for index in indices])
    new = np.asarray([updated.anchors[index].point for index in indices])
    routes = [v1_after, [anchor.point for anchor in request.anchors], [anchor.point for anchor in updated.anchors]]
    routes.extend(row["reference"] or row["corridor"] for row in repaired.values())
    return {"file": bpy.data.filepath, "source_sha256": source_hash, "fixed_indices": list(indices),
            "original_pins": old.tolist(), "fixed_pins": new.tolist(),
            "pin_displacements": np.linalg.norm(new - old, axis=1).tolist(), "safe_candidates": len(safe),
            "anchors_original": [list(anchor.point) for anchor in request.anchors],
            "anchors_fixed": [list(anchor.point) for anchor in updated.anchors],
            "original": original, "repaired": repaired, "v1_after": v1_after,
            "nearby_triangles": base._nearby(snapshot, routes)}


def main():
    args = _arguments(); record = _record(args); output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_PACKAGE42_FIXED_PINS", json.dumps(record["pin_displacements"]), flush=True)


main()
