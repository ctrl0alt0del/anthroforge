"""Read-only real-Blender benchmark for the isolated V3 native operation executor."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fibers", default="FIBER_1,FIBER_14")
    parser.add_argument("--mode", choices=("direct", "operations", "coordinator", "coordinator-live"),
                        default="direct")
    parser.add_argument("--native-threads", type=int, default=4)
    parser.add_argument("--collection-ms", type=float, default=.25)
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


def _activate_backend():
    from anthroforge.core.vcp.v3.native_operation_experiment import EXPERIMENT_DLL, _set_backend
    _set_backend(EXPERIMENT_DLL)


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root") and
                hasattr(obj, "af_vcp_system"))


def _fibers(root, names):
    wanted = set(names)
    return tuple(row for row in root.af_vcp_system.fibers if row.id in wanted or row.name in wanted)


def _capture_request(root, scene, fiber):
    from anthroforge.core.visualization.fiber_refinement import _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request
    runtime = _prepared_session(root, scene, fiber, "FINAL")
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: raise RuntimeError(runtime.invalid_reason or runtime.runtime_error)
    request = _request(runtime); runtime.cancel()
    return request


def _capture_all(root, scene, fibers):
    started = perf_counter(); rows = tuple(_capture_request(root, scene, row) for row in fibers)
    return rows, 1000.0 * (perf_counter() - started)


def _sessions(requests):
    from anthroforge.core.vcp.v3.production import begin_v3
    return tuple(begin_v3(request, preview=False) for request in requests)


def _prime(sessions):
    started = perf_counter()
    for session in sessions:
        while not session.done and session.phase != "SOLVE": session.step()
    return 1000.0 * (perf_counter() - started)


def _direct(sessions):
    started = perf_counter(); steps = 0
    while any(not row.done for row in sessions):
        for row in sessions:
            if not row.done: row.step(); steps += 1
    return SimpleNamespace(elapsed_ms=1000.0 * (perf_counter() - started), waves=0, jobs=0,
        workers_used=1, measures=0, structurals=0, sweeps=0, steps=steps)


def _solve(args, sessions):
    if args.mode == "direct": return _direct(sessions)
    if args.mode == "coordinator-live": return _live_coordinator(sessions, args.collection_ms)
    from anthroforge.core.vcp.v3.native_operation_experiment import V3NativeOperationExperiment
    experiment = V3NativeOperationExperiment(args.collection_ms, args.mode == "coordinator")
    solved = experiment.run(sessions)
    if args.mode != "coordinator": return solved
    try: replay = experiment.replay()
    finally: experiment.release_trace()
    return SimpleNamespace(**solved.__dict__, coordinator=replay)


def _live_coordinator(sessions, collection_ms):
    from anthroforge.core.vcp.v3.native_operation_experiment import V3NativeCoordinatorLiveExperiment
    return V3NativeCoordinatorLiveExperiment(collection_ms).run(sessions)


def _point_hash(points):
    values = np.ascontiguousarray(points, dtype=np.float64)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _result(session):
    result = session.package.result; diagnostics = result.diagnostics
    return {"point_hash": _point_hash(result.points), "termination": result.termination.value,
            "validated": bool(result.validated), "accepted": diagnostics.accepted_steps,
            "rejected": diagnostics.rejected_steps, "count": len(result.points),
            "timing": _timing(session, diagnostics)}


def _timing(session, diagnostics):
    names = ("native_contact_ms", "native_solve_ms", "native_ccd_ms", "native_validation_ms")
    values = {name: float(getattr(diagnostics, name, 0.0) or 0.0) for name in names}
    values["sqp_total_ms"] = sum(float(row.state.sqp_solve_ms) for row in session.spans)
    return values


def _executor(report):
    names = ("waves", "jobs", "workers_used", "measures", "structurals", "sweeps", "steps")
    output = {name: int(getattr(report, name, 0)) for name in names}
    replay = getattr(report, "coordinator", None)
    if replay is not None: output.update(_coordinator(replay))
    return output


def _coordinator(replay):
    row = replay.coordinator
    return {"coordinator_ms": row.elapsed_ms, "coordinator_operations": replay.operations,
        "coordinator_exact": replay.exact_operations, "coordinator_streams": row.streams,
        "contact_jobs": row.contact_jobs, "validation_jobs": row.validation_jobs,
        "structural_jobs": row.structural_jobs, "ccd_broad_jobs": row.ccd_broad_jobs,
        "ccd_pair_jobs": row.ccd_pair_jobs, "coordinator_workers": row.workers_used,
        "contact_mismatches": replay.contact_mismatches,
        "structural_mismatches": replay.structural_mismatches,
        "sweep_mismatches": replay.sweep_mismatches,
        "maximum_safe_delta": replay.maximum_safe_delta,
        "more_permissive_sweeps": replay.more_permissive_sweeps,
        "valid_mismatches": replay.valid_mismatches,
        "baseline_validation_failures": replay.baseline_validation_failures,
        "static_validation_failures": replay.static_validation_failures}


def _report(args, source, capture_ms, setup_ms, result, fibers, sessions):
    return {"mode": args.mode, "native_threads": args.native_threads,
        "collection_ms": args.collection_ms, "file": source, "hash_before": _hash(source),
        "hash_after": _hash(source), "capture_ms": capture_ms, "setup_ms": setup_ms,
        "solve_ms": result.elapsed_ms, "executor": _executor(result),
        "results": {fiber.id: _result(session) for fiber, session in zip(fibers, sessions)}}


def main():
    args = _args(); os.environ["AF_FIBER_ENGINE"] = "V3"
    os.environ["AF_FIBER_NATIVE_THREADS"] = str(args.native_threads)
    _activate_backend(); _ensure_addon(); scene = bpy.context.scene; root = _root(scene)
    names = tuple(value.strip() for value in args.fibers.split(",") if value.strip())
    fibers = _fibers(root, names); source = bpy.data.filepath
    requests, capture_ms = _capture_all(root, scene, fibers); sessions = _sessions(requests)
    setup_ms = _prime(sessions); result = _solve(args, sessions)
    print("AF_V3_NATIVE_OPS=" + json.dumps(
        _report(args, source, capture_ms, setup_ms, result, fibers, sessions), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
