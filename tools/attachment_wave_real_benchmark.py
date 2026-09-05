"""Read-only real Blender benchmark for dependency-wave attachment propagation."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

import bpy
import numpy as np


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--file", required=True)
    parser.add_argument("--mode", choices=("native", "serial-native", "legacy"), required=True)
    parser.add_argument("--values", default="7,1"); parser.add_argument("--output", required=True)
    parser.add_argument("--post-serial-check", action="store_true")
    parser.add_argument("--resolver-check", action="store_true")
    parser.add_argument("--surface-check", action="store_true")
    parser.add_argument("--geometry-check", action="store_true")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _register():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"): anthroforge.register()


def _install_executor(mode):
    if mode == "native": return
    from anthroforge.core.scp_runtime import attachment_wave_runtime as runtime
    original = runtime.apply_attachment_wave
    if mode == "serial-native":
        runtime.apply_attachment_wave = lambda *args, **kwargs: _serial_native(original, args, kwargs)
    else: runtime.apply_attachment_wave = _legacy


def _serial_native(original, args, kwargs):
    from anthroforge.core.vcp.attachment_wave import AttachmentExecutorKind
    return original(*args, **dict(kwargs, executor=AttachmentExecutorKind.SERIAL_REFERENCE))


def _legacy(sync, root, scene, scps, targets, parents, fibers=(), blocked=(), backsolve=None, executor=None):
    from anthroforge.core.scp_runtime.attachment_wave_runtime import _serial_fallback
    _ = executor
    return _serial_fallback(sync, root, scene, scps, targets, parents, fibers,
                            blocked, backsolve, 0.0, "BENCHMARK_LEGACY")


def _file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def _root():
    from anthroforge.core.utils import get_af_root
    return get_af_root(bpy.context.scene)


def _points(root):
    from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
    scene = bpy.context.scene; values = {}
    for fiber in root.af_vcp_system.fibers:
        rows = persisted_fiber_points(scene, root.name, fiber.id) or ()
        values[str(fiber.id)] = tuple(tuple(float(cell) for cell in point) for point in rows)
    return values


def _matrices(root):
    from anthroforge.core.scp_runtime.common import find_transform_scp_obj, matrix_flat16
    scene = bpy.context.scene; values = {}
    for scp in root.af_scp_system.scps:
        obj = find_transform_scp_obj(scene, root.name, scp.id)
        values[str(scp.id)] = () if obj is None else tuple(matrix_flat16(obj.matrix_world))
    return values


def _fiber_targets(root):
    from anthroforge.core.vcp.fiber_node_attachment_codec import decode_node_attachments
    values = {}
    for fiber in root.af_vcp_system.fibers:
        payload = decode_node_attachments(fiber.node_attachments_json)
        values[str(fiber.id)] = () if payload is None else tuple(sorted({row.target_id for row in payload.nodes}))
    return values


def _surface_state(root):
    from anthroforge.core.scp_runtime.common import find_geometry_mesh_scp_obj
    depsgraph = bpy.context.evaluated_depsgraph_get(); values = {}
    for scp in root.af_scp_system.scps:
        obj = find_geometry_mesh_scp_obj(bpy.context.scene, root.name, scp.id)
        if obj is not None: values[str(scp.id)] = _evaluated_surface(obj, depsgraph)
    return values


def _scp_meta(root):
    from anthroforge.core.scp_runtime.common import find_geometry_mesh_scp_obj, find_transform_scp_obj
    values = {}
    for scp in root.af_scp_system.scps:
        geo = find_geometry_mesh_scp_obj(bpy.context.scene, root.name, scp.id)
        transform = find_transform_scp_obj(bpy.context.scene, root.name, scp.id)
        values[str(scp.id)] = {"name": str(scp.name), "parent": str(scp.parent_id),
            "geometry": "" if geo is None else geo.name, "transform": "" if transform is None else transform.name,
            "same_role": geo == transform, "modifiers": [] if geo is None else [row.type for row in geo.modifiers]}
    return values


def _evaluated_surface(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh()
    try:
        vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", vertices); matrix = np.asarray(evaluated.matrix_world)
        return vertices.reshape((-1, 3)), matrix
    finally: evaluated.to_mesh_clear()


def _surface_delta(first, second):
    values = {}
    for key in first:
        if key not in second or first[key][0].shape != second[key][0].shape: values[key] = float("inf")
        else: values[key] = float(np.max(np.abs(first[key][0] - second[key][0])))
    return values


def _point_delta(first, second):
    if len(first) != len(second): return float("inf")
    return max((sum((a - b) ** 2 for a, b in zip(left, right)) ** .5
                for left, right in zip(first, second)), default=0.0)


def _wave_report(root):
    from anthroforge.core.scp_runtime.attachment_wave_runtime import last_attachment_wave_report
    report = last_attachment_wave_report(root)
    return {} if report is None else dict(report.__dict__)


def _event(root, shortcut, value):
    from anthroforge.core.deps.runtime_trace import request_telemetry
    from anthroforge.core.visualization import fiber_refinement
    started = perf_counter(); shortcut.proxy_float = value
    elapsed = 1000.0 * (perf_counter() - started)
    return {"value": value, "elapsed_ms": elapsed, "wave": _wave_report(root),
            "solver_jobs": len(fiber_refinement._JOBS),
            "telemetry": list(request_telemetry(clear=True))}


def _events(args, root, shortcut, initial_surfaces):
    events = []
    for value in args.values.split(","):
        event = _event(root, shortcut, float(value))
        if args.resolver_check: event["resolver_delta"] = _resolver_check(root)
        if args.surface_check: event["surface_delta"] = _surface_delta(initial_surfaces, _surface_state(root))
        if args.geometry_check: event["geometry"] = {"points": _points(root), "matrices": _matrices(root)}
        events.append(event)
    return tuple(events)


def _result(args, root, initial, initial_matrices, events):
    final, matrices = _points(root), _matrices(root)
    deltas = {key: _point_delta(initial[key], final[key]) for key in initial}
    matrix_deltas = {key: _point_delta((initial_matrices[key],), (matrices[key],)) for key in matrices}
    check = _post_serial_check(root, final) if args.post_serial_check else {}
    return {"mode": args.mode, "events": events, "round_trip_max_delta": deltas,
            "scp_round_trip_max_delta": matrix_deltas, "fiber_targets": _fiber_targets(root),
            "post_serial_delta": check, "source_hash": _file_hash(args.file),
            "fiber_count": len(initial), "scp_meta": _scp_meta(root)}


def _run(args):
    from anthroforge.core.deps.runtime_trace import clear_request_telemetry, set_request_telemetry
    root = _root(); initial, initial_matrices = _points(root), _matrices(root)
    surfaces = _surface_state(root) if args.surface_check else {}
    clear_request_telemetry(); set_request_telemetry(True)
    shortcut = next(row for row in root.af_shortcut_system.shortcuts if row.name == "Cranium Lobe Width")
    return _result(args, root, initial, initial_matrices, _events(args, root, shortcut, surfaces))


def _post_serial_check(root, before):
    from anthroforge.core.visualization.fiber_node_attachment_runtime import _apply_fiber_node_attachments_serial
    ids = {str(row.id) for row in root.af_vcp_system.fibers}
    _apply_fiber_node_attachments_serial(root, bpy.context.scene, ids); after = _points(root)
    return {key: _point_delta(before[key], after[key]) for key in before}


def _resolver_check(root):
    from anthroforge.core.scp_runtime.attachment_wave_capture import capture_attachment_wave
    from anthroforge.core.scp_runtime.common import scp_prop_map
    from anthroforge.core.vcp.attachment_wave_native import execute_attachment_wave
    from anthroforge.core.vcp.fiber_node_attachment import resolve_fiber_node_attachments
    fibers = tuple(root.af_vcp_system.fibers); scene = bpy.context.scene
    outcome = capture_attachment_wave(root, scene, scp_prop_map(root), (), (), fibers)
    result = execute_attachment_wave(outcome.request); values = {}
    by_id = {str(row.id): row for row in fibers}
    for index, fiber_id in enumerate(outcome.request.fiber_ids):
        fiber = by_id[fiber_id]
        reference = resolve_fiber_node_attachments(root, scene, fiber)
        values[fiber_id] = _point_delta(result.fiber_points[index], reference.points)
    return values


def main():
    args = _args(); before = _file_hash(args.file); _register(); bpy.ops.wm.open_mainfile(filepath=args.file)
    _install_executor(args.mode); resolver = _resolver_check(_root()) if args.resolver_check else {}
    result = _run(args); result["resolver_initial_delta"] = resolver
    result["source_unchanged"] = before == _file_hash(args.file)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("AF_ATTACHMENT_WAVE_BENCH", json.dumps(result, default=str), flush=True)


if __name__ == "__main__":
    main()
