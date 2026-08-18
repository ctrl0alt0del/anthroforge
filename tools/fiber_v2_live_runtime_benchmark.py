"""Exercise the opt-in pin-smoothing V2 through the real refinement runtime."""

import argparse
import json
import os
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.visualization import sync_runner
from anthroforge.core.visualization.fiber_refinement import (drain_fiber_refinements,
                                                              request_fiber_refinement)
from anthroforge.core.vcp.runtime_state import (fiber_eps_pen, fiber_recompute_status)
from anthroforge.tools import fiber_v2_planner_benchmark as common
from anthroforge.tools import fiber_v25_branch2_sweep as sweep


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True)
    parser.add_argument("--fiber-id", default="FIBER_2"); parser.add_argument("--comparison", default="")
    parser.add_argument("--repeats", type=int, default=3)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"):
        return
    import anthroforge
    anthroforge.register()


def _root():
    return next(obj for obj in bpy.context.scene.objects if obj.get("anthroforge_root")
                and hasattr(obj, "af_vcp_system") and len(obj.af_vcp_system.fibers))


def _fiber(root, identifier):
    return next(row for row in root.af_vcp_system.fibers
                if row.id == identifier or row.name == identifier)


def _proxy(root, fiber):
    return next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_proxy")
                and not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name
                and obj.get("af_fiber_id") == fiber.id)


def _points(proxy):
    return json.loads(str(proxy.get("af_fiber_points_world", "[]") or "[]"))


def _measure(call):
    started = perf_counter(); call(); return 1000.0 * (perf_counter() - started)


def _migrate(fiber):
    result = bpy.ops.af.recompute_fiber(fiber_id=fiber.id)
    if result != {"FINISHED"} or not drain_fiber_refinements():
        raise RuntimeError("live V2 migration did not finish")


def _refine(root, fiber, quality="INTERACTIVE"):
    request = request_fiber_refinement(root, bpy.context.scene, fiber, True, quality)
    if not request.ok or not drain_fiber_refinements():
        raise RuntimeError(request.error or "live V2 refinement did not finish")


def _property_edit(fiber):
    fiber.bend_stiffness = min(1.0, float(fiber.bend_stiffness) + 0.01)
    bpy.context.view_layer.update()
    for _index in range(8):
        if sync_runner._PENDING:
            sync_runner._flush_pending()
    if not drain_fiber_refinements():
        raise RuntimeError("property refinement did not drain")


def _state(fiber, proxy):
    return {"status": fiber_recompute_status(fiber), "solver_version": int(fiber.solver_version),
            "max_pen": float(fiber_eps_pen(fiber)), "output_state": proxy.get("af_fiber_output_state"),
            "point_count": len(_points(proxy))}


def _delta(first, second):
    a, b = np.asarray(first, dtype=np.float64), np.asarray(second, dtype=np.float64)
    return None if a.shape != b.shape else float(np.max(np.linalg.norm(a - b, axis=1)))


def _comparison(path, points):
    if not path:
        return {}, None
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = record.get("pin_smoothing", {}).get("points", ())
    record["visual"]["v25"] = points
    record["pin_smoothing"]["points"] = points
    return record, _delta(points, expected)


def _runtime_rows(args, root, fiber, proxy):
    cold = _measure(lambda: _migrate(fiber)); committed = _points(proxy)
    migrated = _state(fiber, proxy); warm = [_measure(lambda: _refine(root, fiber)) for _ in range(args.repeats)]
    current = _points(proxy); interactive = _state(fiber, proxy)
    return cold, committed, migrated, warm, current, interactive


def _metric_rows(committed, current, edited):
    return {"migration_metrics": sweep._metrics(committed),
            "interactive_metrics": sweep._metrics(current),
            "property_metrics": sweep._metrics(edited)}


def _record(args, root, fiber, proxy):
    original = _points(proxy)
    cold, committed, migrated, warm, current, interactive = _runtime_rows(args, root, fiber, proxy)
    os.environ["AF_FIBER_DEFER_MS"] = "0"
    edited = _measure(lambda: _property_edit(fiber)); edited_points = _points(proxy)
    visual, delta = _comparison(args.comparison, current)
    payload = {"file": bpy.data.filepath, "file_sha256": common._file_hash(bpy.data.filepath),
               "fiber": fiber.id, "cold_migration_ms": cold, "warm_refinement_ms": warm,
               "property_full_cycle_ms": edited, "state_after_migration": migrated,
               "state_after_interactive": interactive, "state_after_property": _state(fiber, proxy),
               "original_points": original, "committed_points": committed,
               "interactive_points": current, "edited_points": edited_points,
               **_metric_rows(committed, current, edited_points),
               "max_delta_qualified_result": delta}
    return payload if not visual else dict(visual, live_runtime=payload)


def main():
    _ensure_addon(); args = _args(); root = _root(); fiber = _fiber(root, args.fiber_id)
    bpy.context.view_layer.objects.active = root; root.select_set(True)
    record = _record(args, root, fiber, _proxy(root, fiber))
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_LIVE " + json.dumps(record.get("live_runtime", record), default=str), flush=True)


if __name__ == "__main__":
    main()
