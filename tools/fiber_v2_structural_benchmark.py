"""Read-only real-file benchmark for the isolated Fiber V2 structural core."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
import statistics
import sys
import time

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (
    StructuralFactorCache, V2Settings, V2Topology, solve_structural)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--counts", default="64,128,256,512")
    parser.add_argument("--repeats", type=int, default=20)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _root():
    roots = [obj for obj in bpy.data.objects if hasattr(obj, "af_vcp_system")]
    return next((obj for obj in roots if len(obj.af_vcp_system.fibers)), None)


def _fiber(root, fiber_id):
    return next((item for item in root.af_vcp_system.fibers if item.id == fiber_id), None)


def _proxy(root, fiber_id):
    return next((obj for obj in bpy.context.scene.objects
                 if obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy")
                 and obj.get("af_root_name") == root.name
                 and obj.get("af_fiber_id") == fiber_id), None)


def _stored_points(root, fiber_id):
    proxy = _proxy(root, fiber_id)
    raw = "" if proxy is None else str(proxy.get("af_fiber_points_world", "") or "")
    points = np.asarray(json.loads(raw), dtype=float) if raw else np.empty((0, 3))
    if points.ndim != 2 or points.shape[1:] != (3,) or len(points) < 2:
        raise RuntimeError(f"{fiber_id} has no persisted centerline")
    return points


def _arc_data(points, cyclic):
    source = np.vstack((points, points[0])) if cyclic else points
    lengths = np.linalg.norm(np.diff(source, axis=0), axis=1)
    distances = np.concatenate(([0.0], np.cumsum(lengths)))
    return source, distances


def _resample(points, count, cyclic):
    source, distances = _arc_data(points, cyclic)
    targets = np.linspace(0.0, distances[-1], count, endpoint=not cyclic)
    return np.column_stack([np.interp(targets, distances, source[:, axis])
                            for axis in range(3)])


def _topology(fiber):
    return V2Topology.CYCLIC if str(fiber.topology_mode) == "LOOP" else V2Topology.OPEN


def _anchor_count(fiber, topology):
    if topology is V2Topology.CYCLIC:
        return len(tuple(fiber.loop_anchors))
    return len(tuple(fiber.mid_touches)) + 2


def _pin_indices(count, anchors, topology):
    if topology is V2Topology.CYCLIC:
        return np.floor(np.arange(anchors) * count / max(1, anchors)).astype(int)
    return np.rint(np.linspace(0, count - 1, anchors)).astype(int)


def _pins(reference, anchors, topology):
    indices = _pin_indices(len(reference), anchors, topology)
    return {int(index): reference[index].copy() for index in indices}


def _settings(fiber, count, topology):
    return V2Settings(topology=topology, node_count=count,
                      length_weight=float(fiber.stretch_stiffness),
                      curvature_weight=float(fiber.bend_stiffness))


def _timings(call, repeats):
    values, result = [], None
    for _index in range(max(1, repeats)):
        started = time.perf_counter(); result = call()
        values.append(1000.0 * (time.perf_counter() - started))
    return values, result


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(np.ceil(fraction * len(ordered))) - 1)
    return float(ordered[index])


def _summary(values):
    return {"median_ms": float(statistics.median(values)),
            "p95_ms": _percentile(values, 0.95), "max_ms": float(max(values))}


def _metrics(reference, result, pins, cache, cold, warm, topology):
    delta = np.linalg.norm(result.points - reference, axis=1)
    cyclic = topology is V2Topology.CYCLIC
    return {"cold": _summary(cold), "warm": _summary(warm),
            "factor_bytes": cache.stats()["bytes"], "energy": result.energy.total,
            "stationarity": result.stationarity_residual,
            "max_displacement": float(delta.max()), "mean_displacement": float(delta.mean()),
            "input_length": _length(reference, cyclic),
            "output_length": _length(result.points, cyclic),
            "pin_indices": sorted(pins)}


def _length(points, cyclic=False):
    source = np.vstack((points, points[0])) if cyclic else points
    return float(np.linalg.norm(np.diff(source, axis=0), axis=1).sum())


def _benchmark_count(points, fiber, count, topology, repeats):
    reference = _resample(points, count, topology is V2Topology.CYCLIC)
    pins = _pins(reference, _anchor_count(fiber, topology), topology)
    settings = _settings(fiber, count, topology)
    cold, _unused = _timings(lambda: solve_structural(
        reference, pins, settings, StructuralFactorCache()), repeats)
    cache = StructuralFactorCache(); solve_structural(reference, pins, settings, cache)
    warm, result = _timings(lambda: solve_structural(reference, pins, settings, cache), repeats)
    metrics = _metrics(reference, result, pins, cache, cold, warm, topology)
    return reference, result, pins, metrics


def _file_hash(path):
    digest = sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _visual_payload(reference, result, pins):
    return {"input": reference.tolist(), "structural": result.points.tolist(),
            "pins": [reference[index].tolist() for index in sorted(pins)]}


def _record(args, root, fiber, points):
    topology = _topology(fiber); rows, visual = {}, None
    for count in [int(value) for value in args.counts.split(",") if value.strip()]:
        reference, result, pins, metrics = _benchmark_count(
            points, fiber, count, topology, args.repeats)
        rows[str(count)] = metrics
        if count == int(fiber.node_count):
            visual = _visual_payload(reference, result, pins)
    return _record_payload(args, root, fiber, topology, rows, visual)


def _record_payload(args, root, fiber, topology, rows, visual):
    path = str(bpy.data.filepath)
    return {"file": path, "file_sha256": _file_hash(path), "root": root.name,
            "fiber_id": fiber.id, "fiber_name": fiber.name, "topology": topology.value,
            "stored_count": int(fiber.node_count), "weights": {
                "length": float(fiber.stretch_stiffness),
                "curvature": float(fiber.bend_stiffness)},
            "blender": bpy.app.version_string, "python": platform.python_version(),
            "processor": platform.processor(), "repeats": args.repeats,
            "counts": rows, "visual": visual}


def main():
    args = _arguments(); root = _root()
    if root is None:
        raise RuntimeError("No AnthroForge root with Fibers was found")
    fiber = _fiber(root, args.fiber_id)
    if fiber is None:
        raise RuntimeError(f"Fiber {args.fiber_id} was not found")
    record = _record(args, root, fiber, _stored_points(root, fiber.id))
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_STRUCTURAL", json.dumps(record["counts"]), flush=True)


main()
