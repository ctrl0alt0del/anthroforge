"""Read-only full-cycle benchmark for serial versus coordinated V3 Fibers."""

import argparse
import cProfile
import hashlib
import json
import os
from pathlib import Path
import pstats
import sys
from time import perf_counter

import bpy


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fibers", default="FIBER_1,FIBER_14")
    parser.add_argument("--mode", choices=("serial", "auto", "batch"), default="auto")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--legacy-runtime", action="store_true")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge
    anthroforge.register()


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root") and
                hasattr(obj, "af_vcp_system"))


def _fibers(root, names):
    wanted = set(names)
    return tuple(row for row in root.af_vcp_system.fibers if row.id in wanted or row.name in wanted)


def _proxy(scene, root, fiber):
    return next((obj for obj in scene.objects if obj.get("af_fiber_proxy") and
                 not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name and
                 obj.get("af_fiber_id") == fiber.id), None)


def _points(proxy):
    return json.loads(str(proxy.get("af_fiber_points_world", "[]") or "[]")) if proxy else []


def _point_hash(points):
    text = json.dumps(points, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _result(scene, root, fiber, request):
    from anthroforge.core.vcp.runtime_state import fiber_recompute_status
    points = _points(_proxy(scene, root, fiber))
    return {"status": fiber_recompute_status(fiber), "count": len(points),
            "point_hash": _point_hash(points), "diagnostics": _diagnostics(request)}


def _diagnostics(request):
    value = request.job.session.result().diagnostics
    names = ("accepted_steps", "rejected_steps", "native_contact_ms", "native_solve_ms",
             "native_ccd_ms", "native_validation_ms", "ccd_candidate_pairs", "ccd_tested_pairs")
    return {name: getattr(value, name, None) for name in names}


def _run(args):
    from anthroforge.core.visualization import fiber_refinement
    if args.legacy_runtime: _enable_legacy_runtime(fiber_refinement)
    scene = bpy.context.scene; root = _root(scene)
    names = tuple(value.strip() for value in args.fibers.split(",") if value.strip())
    fibers = _fibers(root, names); started = perf_counter(); requests = []
    for fiber in fibers:
        requests.append(fiber_refinement.request_fiber_refinement(root, scene, fiber, False, "FINAL"))
    drained = fiber_refinement.drain_fiber_refinements()
    elapsed = 1000.0 * (perf_counter() - started)
    return _report(args, scene, root, fibers, requests, drained, elapsed, fiber_refinement)


def _enable_legacy_runtime(refinement):
    refinement._is_v3_job = lambda _job: False
    refinement._job_geometry_current = lambda job, force=False: (
        refinement._current_geometry_signature(job.session) == job.geometry_signature)


def _report(args, scene, root, fibers, requests, drained, elapsed, refinement):
    path = bpy.data.filepath; source = _hash(path)
    return {"mode": args.mode, "file": path, "hash_before": source, "hash_after": _hash(path),
            "requested": [row.id for row in fibers], "request_ok": [row.ok for row in requests],
            "drained": drained, "full_cycle_ms": elapsed,
            "batch": refinement.fiber_refinement_batch_stats(),
            "results": {row.id: _result(scene, root, row, request)
                        for row, request in zip(fibers, requests)}}


def main():
    args = _args(); os.environ["AF_FIBER_ENGINE"] = "V3"
    modes = {"serial": "0", "auto": "AUTO", "batch": "1"}
    os.environ["AF_FIBER_V3_BATCH"] = modes[args.mode]
    _ensure_addon(); result = _profiled_run(args) if args.profile else _run(args)
    print("AF_V3_BATCH_BENCHMARK=" + json.dumps(result, sort_keys=True), flush=True)


def _profiled_run(args):
    profile = cProfile.Profile(); profile.enable(); result = _run(args); profile.disable()
    stats = pstats.Stats(profile).strip_dirs().sort_stats("cumulative")
    stats.print_stats(35)
    return result


if __name__ == "__main__":
    main()
