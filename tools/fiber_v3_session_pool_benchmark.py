"""Read-only pure-data benchmark for the isolated V3 session-pool experiment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fibers", default="FIBER_1,FIBER_14")
    parser.add_argument("--mode", choices=("serial", "pool"), default="serial")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--quantum", type=int, default=4)
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


def _capture_request(root, scene, fiber):
    from anthroforge.core.visualization.fiber_refinement import _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request
    runtime = _prepared_session(root, scene, fiber, "FINAL")
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: raise RuntimeError(runtime.invalid_reason or runtime.runtime_error)
    request = _request(runtime); runtime.cancel()
    return request


def _capture_all(root, scene, fibers):
    started = perf_counter()
    rows = tuple(_capture_request(root, scene, fiber) for fiber in fibers)
    return rows, 1000.0 * (perf_counter() - started)


def _sessions(requests):
    from anthroforge.core.vcp.v3.production import begin_v3
    return tuple(begin_v3(request, preview=False) for request in requests)


def _prime(sessions):
    started = perf_counter()
    for session in sessions:
        while not session.done and session.phase != "SOLVE": session.step()
    return 1000.0 * (perf_counter() - started)


def _solve(args, sessions):
    from anthroforge.core.vcp.v3.session_pool_experiment import (
        V3SessionPoolExperiment, run_v3_sessions_serial)
    if args.mode == "serial": return run_v3_sessions_serial(sessions, args.quantum)
    return V3SessionPoolExperiment(args.workers, args.quantum).run(sessions)


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


def _report(args, source, capture_ms, setup_ms, pool, fibers, sessions):
    return {"mode": args.mode, "workers": args.workers, "quantum": args.quantum,
            "file": source, "hash_before": _hash(source), "hash_after": _hash(source),
            "capture_ms": capture_ms, "setup_ms": setup_ms, "solve_ms": pool.elapsed_ms,
            "steps": pool.steps, "tasks": pool.tasks, "threads": pool.thread_ids,
            "session_threads": pool.session_threads,
            "results": {fiber.id: _result(session) for fiber, session in zip(fibers, sessions)}}


def main():
    args = _args(); os.environ["AF_FIBER_ENGINE"] = "V3"
    _ensure_addon(); scene = bpy.context.scene; root = _root(scene)
    names = tuple(value.strip() for value in args.fibers.split(",") if value.strip())
    fibers = _fibers(root, names); source = bpy.data.filepath
    requests, capture_ms = _capture_all(root, scene, fibers); sessions = _sessions(requests)
    setup_ms = _prime(sessions); pool = _solve(args, sessions)
    print("AF_V3_SESSION_POOL=" + json.dumps(
        _report(args, source, capture_ms, setup_ms, pool, fibers, sessions), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
