"""Profile Package 4 phases on one read-only Blender production Fiber."""

import argparse
import cProfile
from hashlib import sha256
import json
from pathlib import Path
import pstats
import statistics
import sys
from time import perf_counter

import bpy
import numpy as np

from anthroforge.core.vcp.v2 import (build_triangle_snapshot, plan_reference,
                                     plan_reference_v41, plan_reference_v43)
from anthroforge.core.vcp.v2 import collision as collision_module
from anthroforge.core.vcp.v2 import collision_native as native_module
from anthroforge.core.vcp.v2 import planner as planner_module
from anthroforge.tools import fiber_v2_planner_benchmark as bench


class _Trace:
    def __init__(self):
        self.rows, self.stack = {}, []

    def reset(self):
        self.rows.clear(); self.stack.clear()

    def enter(self, label):
        self.stack.append([label, perf_counter(), 0.0])

    def leave(self):
        label, started, child = self.stack.pop(); elapsed = perf_counter() - started
        row = self.rows.setdefault(label, [0, 0.0, 0.0])
        row[0] += 1; row[1] += elapsed; row[2] += elapsed - child
        if self.stack:
            self.stack[-1][2] += elapsed

    def wrap(self, module, name, label):
        original = getattr(module, name)
        def timed(*args, **kwargs):
            self.enter(label)
            try:
                return original(*args, **kwargs)
            finally:
                self.leave()
        setattr(module, name, timed)

    def snapshot(self):
        return {key: {"calls": row[0], "inclusive_ms": row[1] * 1000.0,
                      "exclusive_ms": row[2] * 1000.0}
                for key, row in self.rows.items()}


_PLANNER_PHASES = (
    ("_edge_clear", "direct_and_single_edge"),
    ("_surface_route", "surface_route"),
    ("_compatibility_candidates", "compatibility_candidates"),
    ("_search_compatibility", "compatibility_search"),
    ("_search_compatibility_v41", "compatibility_search_v41"),
    ("_roadmap_candidates", "roadmap_candidates"),
    ("_search_roadmap", "roadmap_search"),
    ("_search_roadmap_v41", "roadmap_search_v41"),
    ("_search_native_lazy", "native_lazy_search"),
    ("_native_edge_states", "native_edge_validation"),
    ("_shortcut_route", "shortcut"),
    ("_exact_handoff", "exact_count_handoff"),
    ("_validated_result", "final_result_and_validation"),
)

_COLLISION_PHASES = (
    ("validate_static_clearance", "static_clearance"),
    ("validate_segment_clearance_batch", "segment_batch_clearance"),
)

_NATIVE_PHASES = (
    ("native_candidates", "native_broad_phase"),
    ("native_distances", "native_distance"),
    ("native_inside", "native_containment"),
)


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiber-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--version", choices=("package4", "package41", "package43"), default="package4")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _install(trace):
    for name, label in _PLANNER_PHASES:
        trace.wrap(planner_module, name, label)
    for name, label in _COLLISION_PHASES:
        trace.wrap(planner_module, name, label)
    for name, label in _NATIVE_PHASES:
        trace.wrap(collision_module, name, label)


def _trace_runs(call, repeats, trace):
    times, rows, values = [], [], []
    for _index in range(repeats):
        trace.reset(); started = perf_counter(); values.append(call())
        times.append(1000.0 * (perf_counter() - started)); rows.append(trace.snapshot())
    return times, rows, values


def _phase_row(rows, label, totals):
    samples = [row.get(label, {}) for row in rows]
    exclusive = [item.get("exclusive_ms", 0.0) for item in samples]
    inclusive = [item.get("inclusive_ms", 0.0) for item in samples]
    calls = [item.get("calls", 0) for item in samples]
    shares = [100.0 * value / max(total, 1.0e-12) for value, total in zip(exclusive, totals)]
    return {"calls_median": statistics.median(calls), "exclusive_ms_median": statistics.median(exclusive),
            "inclusive_ms_median": statistics.median(inclusive), "exclusive_percent_median": statistics.median(shares)}


def _phase_summary(rows, totals):
    labels = sorted({label for row in rows for label in row})
    output = {label: _phase_row(rows, label, totals) for label in labels}
    measured = [sum(row.get(label, {}).get("exclusive_ms", 0.0) for label in labels) for row in rows]
    output["unattributed"] = _unattributed(totals, measured)
    return output


def _unattributed(totals, measured):
    values = [max(0.0, total - known) for total, known in zip(totals, measured)]
    shares = [100.0 * value / max(total, 1.0e-12) for value, total in zip(values, totals)]
    return {"exclusive_ms_median": statistics.median(values),
            "exclusive_percent_median": statistics.median(shares)}


def _profile_rows(call):
    profile = cProfile.Profile(); profile.enable(); call(); profile.disable()
    rows = [_profile_row(key, value) for key, value in pstats.Stats(profile).stats.items()
            if "core\\vcp\\v2" in key[0].replace("/", "\\")]
    return sorted(rows, key=lambda row: row["cumulative_ms"], reverse=True)[:30]


def _profile_row(key, value):
    filename, line, name = key; primitive, calls, own, cumulative, _callers = value
    return {"function": name, "file": Path(filename).name, "line": line,
            "calls": calls, "primitive_calls": primitive,
            "self_ms": own * 1000.0, "cumulative_ms": cumulative * 1000.0}


def _cached_dispatch_times(call, repeats):
    original_load = native_module.load_native
    original_collision = collision_module.collision_backend_status
    original_planner = planner_module.collision_backend_status
    library = original_load(); status = original_collision()
    native_module.load_native = lambda path=None: library
    collision_module.collision_backend_status = lambda path=None: status
    planner_module.collision_backend_status = lambda path=None: status
    try:
        return bench._timed(call, repeats)[0]
    finally:
        native_module.load_native = original_load
        collision_module.collision_backend_status = original_collision
        planner_module.collision_backend_status = original_planner


def _capture(root, fiber, depsgraph):
    started = perf_counter(); colliders = bench._colliders(bpy.context.scene, root, depsgraph)
    snapshot = build_triangle_snapshot(colliders)
    return colliders, snapshot, 1000.0 * (perf_counter() - started)


def _snapshot_hash(snapshot):
    digest = sha256()
    for value in (snapshot.vertices, snapshot.triangles):
        digest.update(np.ascontiguousarray(value).tobytes())
    digest.update("\0".join(map(str, snapshot.face_owners)).encode("utf-8"))
    return digest.hexdigest().upper()


def _request_manifest(request, snapshot):
    anchors = [{"point": list(row.point), "owner": row.owner_id, "role": row.role.value,
                "authored_index": row.authored_index} for row in request.anchors]
    colliders = [{"id": row.collider_id, "owner": row.owner_id,
                  "vertices": len(row.vertices), "triangles": len(row.triangles)}
                 for row in request.colliders]
    return {"snapshot_sha256": _snapshot_hash(snapshot), "anchors": anchors,
            "colliders": colliders, "settings": _settings_manifest(request.settings)}


def _settings_manifest(settings):
    return {"topology": settings.topology.value, "quality": settings.quality.value,
            "node_count": settings.node_count, "max_steps": settings.max_accepted_steps,
            "length_weight": settings.length_weight, "curvature_weight": settings.curvature_weight,
            "data_weight": settings.fidelity_weight}


def _record(args):
    root = bench._root(); fiber = bench._fiber(root, args.fiber_id)
    depsgraph = bpy.context.evaluated_depsgraph_get(); colliders, snapshot, capture_ms = _capture(root, fiber, depsgraph)
    anchors, legacy = bench._open_anchors(root, fiber, depsgraph)
    request = bench._request(root, fiber, anchors, colliders); planner = _planner(args.version)
    v1_times, _v1 = bench._timed(lambda: bench._v1_plan(root, fiber, legacy, depsgraph), args.repeats)
    v2_times, _v2 = bench._timed(lambda: planner(request, snapshot), args.repeats)
    return _profile_payload(args, root, fiber, request, snapshot, capture_ms, v1_times, v2_times, planner)


def _planner(version):
    if version == "package43":
        return plan_reference_v43
    return plan_reference_v41 if version == "package41" else plan_reference


def _profile_payload(args, root, fiber, request, snapshot, capture_ms, v1_times, v2_times, planner):
    trace = _Trace(); _install(trace)
    call = lambda: planner(request, snapshot)
    traced, rows, values = _trace_runs(call, args.repeats, trace)
    cached_dispatch = _cached_dispatch_times(call, args.repeats)
    return {"file": bpy.data.filepath, "file_sha256": bench._file_hash(bpy.data.filepath),
            "planner_version": args.version,
            "fiber_id": fiber.id, "triangles": len(snapshot.triangles), "snapshot_capture_ms": capture_ms,
            "manifest": _request_manifest(request, snapshot),
            "v1": bench._summary(v1_times), "v2": bench._summary(v2_times),
            "v2_traced": bench._summary(traced), "phases": _phase_summary(rows, traced),
            "cached_native_dispatch": bench._summary(cached_dispatch),
            "mode": values[-1].mode.value, "termination": values[-1].termination.value,
            "diagnostics": vars(values[-1].diagnostics), "cprofile_top": _profile_rows(call)}


def main():
    args = _arguments(); record = _record(args)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print("AF_V2_PROFILE", json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
