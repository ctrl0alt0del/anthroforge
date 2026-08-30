"""Read-only production V3 native-cache and full-solve benchmark."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser();parser.add_argument("--fibers", default="FIBER_1")
    parser.add_argument("--output", required=True);parser.add_argument("--repeats", type=int, default=3)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge;anthroforge.register()


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root") and hasattr(obj, "af_vcp_system"))


def _fibers(root, names):
    wanted = {row.strip().upper() for row in names.split(",") if row.strip()}
    return tuple(row for row in root.af_vcp_system.fibers if row.id.upper() in wanted or row.name.upper() in wanted)


def _request(root, scene, fiber):
    from anthroforge.core.visualization.fiber_refinement import _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request as build
    runtime = _prepared_session(root, scene, fiber, "FINAL")
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: raise RuntimeError(runtime.invalid_reason or runtime.runtime_error)
    value = build(runtime);runtime.cancel();return value


def _timed(call):
    started = perf_counter();value = call();return value, 1000.0 * (perf_counter() - started)


def _solve(request):
    from anthroforge.core.vcp.v3.production import solve_v3
    package, elapsed = _timed(lambda: solve_v3(request))
    points = np.ascontiguousarray(package.result.points);diagnostics = package.result.diagnostics
    return {"elapsed_ms": elapsed, "point_hash": hashlib.sha256(points.tobytes()).hexdigest(),
            "termination": package.result.termination.value, "validated": package.result.validated,
            "accepted": diagnostics.accepted_steps, "rejected": diagnostics.rejected_steps,
            "contact_ms": diagnostics.native_contact_ms, "ccd_ms": diagnostics.native_ccd_ms}


def _moved(collider, delta):
    matrix = np.asarray(collider.transform).copy();matrix[0, 3] += delta
    vertices = np.asarray(collider.vertices).copy();vertices[:, 0] += delta
    return replace(collider, vertices=vertices, transform=matrix,
                   generation=tuple(collider.generation) + (f"bench-{delta}",))


def _world_call(colliders, cached=True):
    from anthroforge.core.vcp.v2.collision import (build_native_collision_world_batch,
                                                    cached_native_collision_world_batch)
    function = cached_native_collision_world_batch if cached else build_native_collision_world_batch
    return function(colliders)


def _world_validation(world, request):
    points = np.asarray(request.warm_seed if len(request.warm_seed) else [row.point for row in request.anchors])
    if len(points) < 2: return ()
    edges = tuple((index, index + 1) for index in range(len(points) - 1));owners = (("", ""),) * len(edges)
    result = world.validate(points, edges, owners, 0.0, request.collision_policy.collision_radius)
    return tuple(result.clear), tuple(result.blockers), float(result.minimum)


def _refit_probe(request, repeats):
    from anthroforge.core.vcp.v2.collision import (clear_triangle_snapshot_cache,
        native_collision_cache_stats)
    clear_triangle_snapshot_cache();world, cold = _timed(lambda: _world_call(request.colliders))
    hits = [_timed(lambda: _world_call(request.colliders))[1] for _ in range(repeats)]
    moved = tuple(_moved(row, 1.0e-5) for row in request.colliders);refits = []
    for index in range(repeats):
        rows = moved if index % 2 == 0 else request.colliders
        world, elapsed = _timed(lambda rows=rows: _world_call(rows));refits.append(elapsed)
    world = _world_call(moved);actual = _world_validation(world, replace(request, colliders=moved))
    stats = native_collision_cache_stats();clear_triangle_snapshot_cache()
    clean, rebuild = _timed(lambda: _world_call(moved, False));expected = _world_validation(clean, request)
    return {"cold_ms": cold, "hit_median_ms": median(hits), "refit_median_ms": median(refits),
            "clean_rebuild_ms": rebuild, "refit_matches_clean": actual == expected, "stats": stats}


def _benchmark(root, scene, fiber, repeats):
    from anthroforge.core.vcp.v3.production import clear_v3_caches
    request, capture = _timed(lambda: _request(root, scene, fiber));clear_v3_caches()
    cold = _solve(request);warm = tuple(_solve(request) for _index in range(repeats))
    return {"fiber": fiber.name, "capture_ms": capture, "cold": cold, "warm": warm,
            "world": _refit_probe(request, repeats)}


def main():
    args = _args();source = Path(bpy.data.filepath);before = _hash(source);_ensure_addon()
    scene = bpy.context.scene;root = _root(scene);fibers = _fibers(root, args.fibers)
    reports = tuple(_benchmark(root, scene, row, max(1, args.repeats)) for row in fibers)
    payload = {"source": str(source), "source_hash_before": before,
               "source_hash_after": _hash(source), "fibers": reports}
    Path(args.output).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": args.output, "fibers": len(reports)}));return 0


if __name__ == "__main__":
    raise SystemExit(main())
