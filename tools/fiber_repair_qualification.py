"""Read-only-source qualification runner for production Repair Fibers."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy


def _arguments():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--preview", default=""); parser.add_argument("--recompute", action="store_true")
    parser.add_argument("--runtime-scan", action="store_true")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""): digest.update(block)
    return digest.hexdigest()


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge
    anthroforge.register()


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root") and hasattr(obj, "af_vcp_system"))


def _preflight_rows(scene, root):
    from anthroforge.core.vcp.fiber_anchor_preflight import preflight_fiber_hard_anchors
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    graph = bpy.context.evaluated_depsgraph_get(); solver = register_fiber_sync()._solver; rows = []
    for fiber in root.af_vcp_system.fibers:
        result = preflight_fiber_hard_anchors(root, scene, fiber, solver, graph, "FINAL")
        for row in () if result is None or result.valid else result.violations: rows.append(_pin_row(fiber, row))
    return rows


def _pin_row(fiber, row):
    return {"fiber": str(fiber.id), "role": row.role.value, "index": int(row.authored_index),
            "owner": str(row.owner_id), "blocker": str(row.blocker_id), "relation": str(row.relation)}


def _scan(scene, root):
    from anthroforge.core.vcp.fiber_pin_repair import begin_fiber_pin_repair
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    graph = bpy.context.evaluated_depsgraph_get()
    session = begin_fiber_pin_repair(root, scene, graph, register_fiber_sync()._solver); slices = []; phases = {}
    while not session.done:
        phase = _scan_phase(session); started = perf_counter(); session.step(12.0)
        elapsed = 1000.0 * (perf_counter() - started); slices.append(elapsed); phases.setdefault(phase, []).append(elapsed)
    return session, _slice_report(slices, phases)


def _runtime_scan(scene, root):
    from anthroforge.core.visualization import fiber_repair_runtime as runtime
    graph = bpy.context.evaluated_depsgraph_get(); token = runtime.begin_fiber_repair(root, scene, graph)
    operation = runtime.fiber_repair_operation(token); slices = []; phases = {}
    while operation.phase == "SCANNING":
        phase = _scan_phase(operation.session); started = perf_counter(); runtime.step_fiber_repair(token, 12.0)
        elapsed = 1000.0 * (perf_counter() - started); slices.append(elapsed); phases.setdefault(phase, []).append(elapsed)
    if operation.phase not in {"READY", "AWAITING_CONFIRMATION"}: raise RuntimeError(operation.error)
    return operation.session, _slice_report(slices, phases)


def _scan_phase(session):
    if session.phase != "REPAIR": return session.phase
    if session.sampler is not None: return "REPAIR_SAMPLER"
    if session.refiner is not None: return "REPAIR_REFINER"
    return "REPAIR_SETUP"


def _slice_report(slices, phases):
    details = {key: {"count": len(rows), "total_ms": sum(rows), "maximum_ms": max(rows),
                     "p95_ms": _p95(rows)} for key, rows in phases.items()}
    return {"count": len(slices), "maximum_ms": max(slices, default=0.0),
            "p95_ms": _p95(slices), "phases": details}


def _p95(values):
    rows = sorted(values)
    return 0.0 if not rows else rows[min(len(rows) - 1, int(0.95 * len(rows)))]


def _repair(scene, root, session):
    from anthroforge.core.vcp.fiber_pin_repair import apply_fiber_pin_repair_plan
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    graph = bpy.context.evaluated_depsgraph_get()
    return apply_fiber_pin_repair_plan(root, scene, session.plan(), register_fiber_sync()._solver, graph)


def _plan_rows(plan):
    return [{"fiber": row.pin.fiber_id, "role": row.pin.role, "index": row.pin.index,
             "old_owner": row.pin.owner, "new_owner": row.candidate.owner,
             "displacement": row.candidate.displacement, "risky": row.risky} for row in plan.repairs]


def _recompute(scene, root):
    from anthroforge.core.visualization.fiber_refinement import (drain_fiber_refinements,
        fiber_refinement_group_state, request_fiber_refinement_group)
    ids = tuple(row.id for row in root.af_vcp_system.fibers); started = perf_counter()
    token = request_fiber_refinement_group(root, scene, ids, "FINAL")
    drained = drain_fiber_refinements(); state = fiber_refinement_group_state(token)
    return {"drained": drained, "elapsed_ms": 1000.0 * (perf_counter() - started), "state": state}


def _save_reload(path):
    if not path: return None
    target = str(Path(path).resolve()); bpy.ops.wm.save_as_mainfile(filepath=target, copy=True)
    bpy.ops.wm.open_mainfile(filepath=target)
    scene = bpy.context.scene; return _preflight_rows(scene, _root(scene))


def _run(args):
    scene = bpy.context.scene; root = _root(scene); source = str(Path(bpy.data.filepath).resolve())
    source_hash = _hash(source); before = _preflight_rows(scene, root)
    session, slices = (_runtime_scan(scene, root) if args.runtime_scan else _scan(scene, root))
    plan = session.plan(); report = _repair(scene, root, session); after = _preflight_rows(scene, root)
    recompute = _recompute(scene, root) if args.recompute else None
    reloaded = _save_reload(args.preview)
    return {"source": source, "hash_before": source_hash, "hash_after": _hash(source),
            "before": before, "plan": _plan_rows(plan), "failures": len(plan.failures),
            "scan_ms": plan.elapsed_ms, "slices": slices, "report": report.__dict__,
            "after": after, "after_reload": reloaded, "recompute": recompute}


def main():
    args = _arguments(); _ensure_addon(); report = _run(args)
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("AF_FIBER_REPAIR_QUALIFICATION=" + json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
