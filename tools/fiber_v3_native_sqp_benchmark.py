"""Read-only Blender benchmark for the isolated native V3 SQP controller."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--fibers", default="FIBER_1")
    parser.add_argument("--output", required=True); parser.add_argument("--no-planner", action="store_true")
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--production-only", action="store_true")
    parser.add_argument("--cap", type=int, default=0)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge; anthroforge.register()


def _set_threads(count):
    if count <= 0: return
    from anthroforge.core.vcp.v2.collision_native import load_native
    if load_native().af_fiber_set_worker_threads(count): raise ValueError("invalid native thread count")


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root") and
                hasattr(obj, "af_vcp_system"))


def _fibers(root, names):
    wanted = {row.strip().upper() for row in names.split(",") if row.strip()}
    return tuple(row for row in root.af_vcp_system.fibers
                 if row.id.upper() in wanted or row.name.upper() in wanted)


def _request(root, scene, fiber):
    from anthroforge.core.visualization.fiber_refinement import _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request
    runtime = _prepared_session(root, scene, fiber, "FINAL")
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: raise RuntimeError(runtime.invalid_reason or runtime.runtime_error)
    value = _request(runtime); runtime.cancel(); return value


def _production(request, planner):
    from anthroforge.core.vcp.v3.production import solve_v3
    started = perf_counter(); package = solve_v3(request, use_planner=planner,
                                                 native_controller=False)
    elapsed = 1000.0 * (perf_counter() - started); points = np.asarray(package.result.points)
    diagnostics = package.result.diagnostics
    return {"points": points, "elapsed_ms": elapsed, "validated": package.result.validated,
        "termination": package.result.termination.value, "accepted": diagnostics.accepted_steps,
        "controller": diagnostics.controller,
        "rejected": diagnostics.rejected_steps, "ccd_ms": diagnostics.native_ccd_ms,
        "ccd_pairs": diagnostics.ccd_candidate_pairs, "ccd_tests": diagnostics.ccd_tested_pairs,
        "contact_ms": diagnostics.native_contact_ms, "validation_ms": diagnostics.native_validation_ms,
        "native_sessions": tuple(dict(row.native_session_stats) for row in package.trace.spans),
        "trajectory": ()}


def _controller(request, planner):
    from anthroforge.core.vcp.v3.production import solve_v3_controller
    started = perf_counter(); package = solve_v3_controller(request, use_planner=planner)
    elapsed = 1000.0 * (perf_counter() - started); diagnostics = package.result.diagnostics
    return {"points": np.asarray(package.result.points), "elapsed_ms": elapsed,
        "validated": package.result.validated, "termination": package.result.termination.value,
        "controller": diagnostics.controller,
        "accepted": diagnostics.accepted_steps, "rejected": diagnostics.rejected_steps,
        "ccd_pairs": diagnostics.ccd_candidate_pairs, "ccd_tests": diagnostics.ccd_tested_pairs,
        "trajectory": ()}


def _native(request, mode, planner):
    from anthroforge.core.vcp.v3.native_sqp_experiment import solve_native_sqp
    started = perf_counter(); report = solve_native_sqp(request, mode, planner)
    total = 1000.0 * (perf_counter() - started)
    return {"points": report.points, "elapsed_ms": report.elapsed_ms, "total_ms": total,
        "validated": report.validated, "termination": "+".join(row.termination for row in report.spans),
        "accepted": sum(row.accepted for row in report.spans),
        "rejected": sum(row.rejected for row in report.spans),
        "ccd_pairs": sum(row.ccd_pairs for row in report.spans),
        "ccd_tests": sum(row.ccd_tests for row in report.spans),
        "trajectory": tuple(row.trajectory for row in report.spans)}


def _summary(row):
    points = row["points"]; clean = {key: value for key, value in row.items() if key != "points"}
    clean["point_hash"] = hashlib.sha256(np.ascontiguousarray(points).tobytes()).hexdigest()
    clean["length"] = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
    clean["trajectory"] = clean["trajectory"]; return clean


def _delta(first, second):
    if first.shape != second.shape: return {"maximum": None, "rms": None}
    values = np.linalg.norm(first - second, axis=1)
    return {"maximum": float(values.max(initial=0.0)), "rms": float(np.sqrt(np.mean(values * values)))}


def _benchmark(root, scene, fiber, planner, experiments=True, cap=0):
    started = perf_counter(); request = _request(root, scene, fiber)
    if cap > 0: request = replace(request, settings=replace(request.settings, max_accepted_steps=cap))
    capture = 1000.0 * (perf_counter() - started); current = _production(request, planner)
    controller = _controller(request, planner)
    if not experiments: return _current_row(fiber, capture, current, controller)
    from anthroforge.core.vcp.v3.native_sqp_experiment import INDEXED_CCD, LEGACY_CCD
    legacy = _native(request, LEGACY_CCD, planner); indexed = _native(request, INDEXED_CCD, planner)
    comparisons = {"current_to_controller": _delta(current["points"], controller["points"]),
        "current_to_legacy": _delta(current["points"], legacy["points"]),
        "current_to_indexed": _delta(current["points"], indexed["points"]),
        "legacy_to_indexed": _delta(legacy["points"], indexed["points"])}
    return {"fiber": fiber.name, "capture_ms": capture, "current": _summary(current),
            "production_controller": _summary(controller),
            "native_legacy": _summary(legacy), "native_indexed": _summary(indexed),
            "comparisons": comparisons, "points": _point_payload(current, legacy, indexed)}


def _current_row(fiber, capture, current, controller):
    return {"fiber": fiber.name, "capture_ms": capture, "current": _summary(current),
            "production_controller": _summary(controller),
            "points": {"current": current["points"].tolist(),
                       "production_controller": controller["points"].tolist()}}


def _point_payload(current, legacy, indexed):
    return {"current": current["points"].tolist(), "native_legacy": legacy["points"].tolist(),
            "native_indexed": indexed["points"].tolist()}


def main():
    args = _args(); source = Path(bpy.data.filepath); before = _hash(source); _ensure_addon(); _set_threads(args.threads)
    scene = bpy.context.scene; root = _root(scene); rows = _fibers(root, args.fibers)
    if not rows: raise RuntimeError("no requested Fibers found")
    reports = tuple(_benchmark(root, scene, row, not args.no_planner,
                    not args.production_only, args.cap) for row in rows)
    payload = {"source": str(source), "source_hash_before": before,
        "source_hash_after": _hash(source), "fibers": reports}
    Path(args.output).write_text(json.dumps(payload, indent=2, allow_nan=True), encoding="utf-8")
    print(json.dumps({"output": args.output, "fibers": len(reports)})); return 0


if __name__ == "__main__":
    raise SystemExit(main())
