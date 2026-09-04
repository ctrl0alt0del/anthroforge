"""Isolated real-file experiments for attachment propagation bottlenecks."""

import argparse
import cProfile
from hashlib import sha256
import io
import json
from pathlib import Path
import pstats
import sys
from dataclasses import replace

import bpy
from mathutils import Vector
import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
import attachment_wave_real_benchmark as bench


_ORIGINAL_REFRESH = None
_HANDLE_INDEX = None
_STENCIL_STATS = []


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--file", required=True)
    parser.add_argument("--variant", choices=_variants(), required=True)
    parser.add_argument("--values", default="7,1,7,1,7,1")
    parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _variants():
    return ("BASE", "FAST_CAPTURE", "FAST_HANDLES", "FAST_BOTH",
            "SHARED_MIRROR", "FAST_ALL", "FAST_EXACT", "FAST_MUSCLE_SIGNATURE",
            "FAST_MUSCLE_INFLATION", "FAST_MUSCLE_BOTH", "PROFILE",
            "BARRIER_FUSION", "CLASSIFY", "STENCIL_STATS", "NO_MUSCLE",
            "SPARSE_STENCILS", "SPARSE_EXACT", "NO_MIRROR", "NO_DOWNSTREAM")


def _install(variant):
    if variant in {"FAST_CAPTURE", "FAST_BOTH", "FAST_ALL", "FAST_EXACT"}: _install_fast_capture()
    if variant in {"FAST_HANDLES", "FAST_BOTH", "FAST_ALL", "FAST_EXACT", "SPARSE_EXACT"}: _install_fast_handles()
    if variant in {"SHARED_MIRROR", "FAST_ALL", "FAST_EXACT", "SPARSE_EXACT"}: _install_shared_mirror()
    if variant in {"FAST_MUSCLE_SIGNATURE", "FAST_MUSCLE_BOTH", "FAST_EXACT", "SPARSE_EXACT"}: _install_fast_muscle_signature()
    if variant in {"FAST_MUSCLE_INFLATION", "FAST_MUSCLE_BOTH"}: _install_fast_muscle_inflation()
    if variant == "BARRIER_FUSION": _install_barrier_fusion()
    if variant == "STENCIL_STATS": _install_stencil_stats()
    if variant in {"SPARSE_STENCILS", "SPARSE_EXACT"}: _install_sparse_stencils()
    if variant in {"NO_MUSCLE", "NO_DOWNSTREAM"}: _install_no_muscle()
    if variant in {"NO_MIRROR", "NO_DOWNSTREAM"}: _install_no_mirror()


def _install_fast_capture():
    from anthroforge.core.scp_runtime import attachment_wave_capture as capture
    capture.build_mesh_collision_data = _fast_surface_payload


def _fast_surface_payload(obj, depsgraph, cache=None):
    _ = cache; evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh()
    if mesh is None or not len(mesh.vertices): return None
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", values)
        return {"verts_local": values.reshape((-1, 3)), "triangles": ()}
    finally: evaluated.to_mesh_clear()


def _install_fast_handles():
    global _ORIGINAL_REFRESH
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    sync = register_fiber_sync(); _ORIGINAL_REFRESH = sync.refresh_selection
    sync.refresh_selection = _fast_refresh


def _fast_refresh(root=None, scene=None, window_manager=None, fiber_ids=None, sync_handles=False):
    _ = window_manager
    if not sync_handles: return _ORIGINAL_REFRESH(root, scene, None, fiber_ids, False)
    root, scene = root, scene or bpy.context.scene
    fiber = _active_fiber(root, scene)
    if fiber is None or str(fiber.id) not in set(fiber_ids or ()): return None
    return _update_active_handles(root, scene, fiber)


def _active_fiber(root, scene):
    from anthroforge.core.visualization.fiber_sync_runtime import _active_fiber
    return _active_fiber(root, scene)


def _update_active_handles(root, scene, fiber):
    from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
    points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    index = _handle_index(root, scene)
    if len(points) != int(fiber.node_count): return _ORIGINAL_REFRESH(root, scene, None, {fiber.id}, True)
    indices = _pin_indices(fiber)
    if indices is None: return _ORIGINAL_REFRESH(root, scene, None, {fiber.id}, True)
    _place_handles(index, fiber, points, indices)


def _handle_index(root, scene):
    global _HANDLE_INDEX
    if _HANDLE_INDEX is None:
        from anthroforge.core.visualization.fiber_sync import register_fiber_sync
        from anthroforge.core.visualization.vcp_object_index import build_vcp_object_index
        vis = register_fiber_sync()._get_vis_collection(scene)
        _HANDLE_INDEX = build_vcp_object_index(vis, root.name)
    return _HANDLE_INDEX


def _pin_indices(fiber):
    from anthroforge.core.vcp.fiber_modes import is_loop_fiber
    from anthroforge.core.vcp.fiber_node_attachment_codec import decode_node_attachments
    payload = decode_node_attachments(fiber.node_attachments_json)
    if payload is None: return None
    bindings = _loop_bindings(fiber) if is_loop_fiber(fiber) else _open_bindings(fiber)
    return _match_bindings(payload.nodes, bindings, is_loop_fiber(fiber))


def _open_bindings(fiber):
    rows = [(fiber.a_parent_id, fiber.a_attach_param)]
    rows.extend((touch.parent_id, touch.attach_param) for touch in fiber.mid_touches)
    rows.append((fiber.b_parent_id, fiber.b_attach_param)); return tuple(rows)


def _loop_bindings(fiber):
    return tuple((row.parent_id, row.attach_param) for row in fiber.loop_anchors)


def _match_bindings(nodes, bindings, cyclic):
    if not bindings: return ()
    if not cyclic: return _match_open(nodes, bindings)
    return _match_ordered(nodes, bindings, 0, len(nodes))


def _match_open(nodes, bindings):
    if not _same_binding(nodes[0], bindings[0]) or not _same_binding(nodes[-1], bindings[-1]): return None
    middle = _match_ordered(nodes, bindings[1:-1], 1, len(nodes) - 1)
    return None if middle is None else (0, *middle, len(nodes) - 1)


def _match_ordered(nodes, bindings, start, stop):
    indices, cursor = [], start
    for binding in bindings:
        match = next((i for i in range(cursor, stop) if _same_binding(nodes[i], binding)), None)
        if match is None: return None
        indices.append(match); cursor = match + 1
    return tuple(indices)


def _same_binding(node, binding):
    return node.target_id == str(binding[0] or "") and node.attach_raw == str(binding[1] or "")


def _place_handles(index, fiber, points, pins):
    from anthroforge.core.vcp.fiber_modes import is_loop_fiber
    rows = _indexed_handles(index, fiber, is_loop_fiber(fiber))
    for handle, point_index in zip(rows, pins):
        if handle is not None: _place(handle, points[point_index])


def _indexed_handles(index, fiber, cyclic):
    fid = str(fiber.id)
    if cyclic: return tuple(index["loop"].get((fid, i)) for i in range(len(fiber.loop_anchors)))
    values = [index["endpoint"].get((fid, "A"))]
    values.extend(index["touch"].get((fid, i)) for i in range(len(fiber.mid_touches)))
    values.append(index["endpoint"].get((fid, "B"))); return tuple(values)


def _place(handle, point):
    from anthroforge.core.scp_runtime.common import mark_applied_matrix
    matrix = handle.matrix_world.copy(); matrix.translation = point
    handle.matrix_world = matrix; mark_applied_matrix(handle)


def _install_no_muscle():
    from anthroforge.core.visualization.muscle_sync import register_muscle_sync
    register_muscle_sync().sync_root_to_scene = lambda *args, **kwargs: None


def _install_no_mirror():
    from anthroforge.core.deps import builtin_drivers
    from anthroforge.core.scp_runtime import sync_runtime
    builtin_drivers.sync_vcp_mirrors = lambda *args, **kwargs: None
    sync_runtime.sync_mirrors = lambda *args, **kwargs: None


def _install_shared_mirror():
    from anthroforge.core.visualization import vcp_mirror_runtime
    vcp_mirror_runtime._copy_mirror_transform = _share_mirror_data


def _share_mirror_data(source, mirror, axis, origin):
    from anthroforge.core.visualization.mirror_rules import mirror_world_matrix
    previous = mirror.data
    if previous is not source.data: mirror.data = source.data; _remove_orphan(previous)
    mirror.matrix_world = mirror_world_matrix(source.matrix_world, axis=axis, origin=origin)
    mirror.hide_select = True


def _remove_orphan(data):
    if data is None or data.users: return
    if isinstance(data, bpy.types.Mesh): bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Curve): bpy.data.curves.remove(data)


def _install_fast_muscle_signature():
    from anthroforge.core.visualization import muscle_sync_helpers
    muscle_sync_helpers._update_mesh_payload = _fast_mesh_payload


def _fast_mesh_payload(obj, verts, faces):
    from anthroforge.core.visualization import muscle_sync_helpers as helpers
    coordinates, topology = _numeric_payload(verts, faces)
    signature = sha256(topology.encode() + coordinates.tobytes()).hexdigest()
    if obj.get("af_mesh_signature") == signature: return None
    if helpers._same_topology(obj, obj.data, verts, topology):
        return helpers._update_mesh_vertices(obj, obj.data, coordinates, signature)
    return helpers._rebuild_mesh(obj, obj.data, verts, faces, signature, topology)


def _numeric_payload(verts, faces):
    coordinates = np.ascontiguousarray(verts, dtype=np.float64).reshape((-1, 3))
    indices = np.ascontiguousarray(faces, dtype=np.int64)
    return coordinates, sha256(indices.tobytes()).hexdigest()


def _install_fast_muscle_inflation():
    from anthroforge.core.visualization import muscle_inflation_modes
    muscle_inflation_modes.apply_inflation_distributed = _vector_inflation


def _vector_inflation(points, muscle):
    from anthroforge.core.visualization.muscle_inflation import _enabled_params
    values = _point_array(points); params = _enabled_params(muscle)
    if params is None or not values.size: return _vector_rows(values)
    normals = _coherent_array(_normal_array(values))
    amounts = _distributed_amounts(values, normals, muscle, params)
    direction = normals if params["sign"] >= 0.0 else -normals
    return _vector_rows(values + direction * amounts[..., None])


def _point_array(points):
    return np.ascontiguousarray([[(p.x, p.y, p.z) for p in row] for row in points], dtype=np.float64)


def _vector_rows(values):
    return [[Vector(point) for point in row] for row in values]


def _normal_array(values):
    m, n = values.shape[:2]; rows = np.arange(m); cols = np.arange(n)
    tv = values[np.minimum(rows + 1, m - 1)] - values[np.maximum(rows - 1, 0)]
    tu = values[:, np.minimum(cols + 1, n - 1)] - values[:, np.maximum(cols - 1, 0)]
    normals = np.cross(tv, tu); lengths = np.linalg.norm(normals, axis=2)
    fallback = values - np.mean(values, axis=(0, 1)); normals[lengths <= 1e-10] = fallback[lengths <= 1e-10]
    return _normalize_array(normals)


def _normalize_array(values):
    lengths = np.linalg.norm(values, axis=2); safe = lengths > 1e-10
    out = np.zeros_like(values); out[..., 2] = 1.0
    out[safe] = values[safe] / lengths[safe, None]
    return out


def _coherent_array(normals):
    m, n = normals.shape[:2]; starts = np.ones(m, dtype=np.float64)
    vertical = np.sum(normals[1:, 0] * normals[:-1, 0], axis=1)
    if m > 1: starts[1:] = np.cumprod(np.where(vertical >= 0.0, 1.0, -1.0))
    edges = np.sum(normals[:, 1:] * normals[:, :-1], axis=2)
    signs = np.ones((m, n), dtype=np.float64)
    if n > 1: signs[:, 1:] = np.cumprod(np.where(edges >= 0.0, 1.0, -1.0), axis=1)
    return normals * (starts[:, None] * signs)[..., None]


def _distributed_amounts(values, normals, muscle, params):
    edge = _edge_array(values.shape[:2], muscle, params)
    fade = _fade_array(values.shape[1], params["length_taper_band"])
    raw = params["amount"] * edge * fade[None, :]
    stability = _neighbor_min(normals, _normal_dot, 1.0)
    radius = _neighbor_min(values, _point_distance, np.inf)
    clamped = np.minimum(raw, np.where(np.isfinite(radius), radius * 2.5, 0.0))
    blend = np.clip(stability / 0.85, 0.0, 1.0)
    return np.where((raw > 0.0) & (stability < 0.85), clamped + (raw - clamped) * blend, np.maximum(raw, 0.0))


def _edge_array(shape, muscle, params):
    m, n = shape; i, j = np.indices((m, n))
    du = np.minimum(j, n - 1 - j); dv = np.full_like(du, 10 ** 9)
    if not bool(muscle.closed_v): dv = np.minimum(i, m - 1 - i)
    t = np.clip(np.minimum(du, dv) / params["b_band"], 0.0, 1.0)
    smooth = (t * t * (3.0 - 2.0 * t)) ** params["b_power"]
    edge = (1.0 - params["b_strength"]) + params["b_strength"] * smooth
    edge[(j == 0) | (j == n - 1) | ((not bool(muscle.closed_v)) & ((i == 0) | (i == m - 1)))] = 0.0
    return edge


def _fade_array(count, band_value):
    j = np.arange(count); band = max(1.0, float(band_value) * max(0.0, count - 1.0))
    u = np.clip(np.minimum(j, np.maximum(0, count - 1 - j)) / band, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _neighbor_min(values, operation, initial):
    result = np.full(values.shape[:2], initial, dtype=np.float64)
    result[1:] = np.minimum(result[1:], operation(values[1:], values[:-1]))
    result[:-1] = np.minimum(result[:-1], operation(values[:-1], values[1:]))
    result[:, 1:] = np.minimum(result[:, 1:], operation(values[:, 1:], values[:, :-1]))
    result[:, :-1] = np.minimum(result[:, :-1], operation(values[:, :-1], values[:, 1:]))
    return result


def _normal_dot(first, second):
    return np.maximum(0.0, np.sum(first * second, axis=2))


def _point_distance(first, second):
    return np.linalg.norm(first - second, axis=2)


def _install_barrier_fusion():
    from anthroforge.core.scp_runtime import attachment_wave_runtime
    attachment_wave_runtime._staged_wave = _single_attachment_capture


def _single_attachment_capture(sync, root, scene, scps, targets, parents, fibers, blocked, backsolve, kind):
    from anthroforge.core.scp_runtime import attachment_wave_runtime as runtime
    state = runtime._wave_state(blocked, ())
    outcome, result = runtime._run_native_phase(root, scene, scps, targets, parents,
        fibers, backsolve, kind, state, None)
    _single_commit_scps(root, scene, scps, outcome, result, state)
    _single_commit_fibers(root, scene, outcome, result, state)
    return runtime._record(root, runtime._state_report(state))


def _single_commit_scps(root, scene, scps, outcome, result, state):
    from anthroforge.core.scp_runtime import attachment_wave_runtime as runtime
    from anthroforge.core.shortcuts.session_state import suppress_next_depsgraph_ids
    changed = runtime._commit_scps(root, scene, outcome, result)
    state["changed"] |= set(changed); runtime._record_scp_failures(scps, outcome, result, state)
    if changed: suppress_next_depsgraph_ids(changed)


def _single_commit_fibers(root, scene, outcome, result, state):
    from anthroforge.core.scp_runtime import attachment_wave_runtime as runtime
    handled, failed, write_ms, refresh_ms = runtime._commit_fibers(root, scene, outcome, result)
    state["commit"] += write_ms + refresh_ms; state["handled"] |= handled; state["failed"] |= failed


def _install_stencil_stats():
    from anthroforge.core.scp_runtime import attachment_wave_runtime
    original = attachment_wave_runtime.capture_attachment_wave
    attachment_wave_runtime.capture_attachment_wave = lambda *a, **k: _record_stencils(original(*a, **k))


def _record_stencils(outcome):
    request = outcome.request; used = [set() for _row in request.surfaces]
    for operation in request.scp_operations: _add_scp_indices(used, operation)
    for operation in request.fiber_operations: _add_indices(used, operation.surface_index, operation.triangle)
    _STENCIL_STATS.append({"surface_vertices": sum(len(row.vertices) for row in request.surfaces),
        "used_vertices": sum(len(row) for row in used), "surfaces": len(used),
        "scp_ops": len(request.scp_operations), "fiber_ops": len(request.fiber_operations)})
    return outcome


def _add_scp_indices(used, operation):
    _add_indices(used, operation.surface_index, operation.triangle)
    _add_indices(used, operation.surface_index, operation.flow_triangle)


def _add_indices(used, surface_index, triangle):
    if surface_index < 0: return
    used[surface_index].update(int(index) for index in triangle if int(index) >= 0)


def _geometry_fingerprints(root):
    from anthroforge.core.scp_runtime.common import indexed_geometry_mesh_scp_obj, scp_object_maps
    from anthroforge.core.utils import depsgraph_for_scene
    scene = bpy.context.scene; objects = scp_object_maps(scene, root.name); graph = depsgraph_for_scene(scene)
    return {str(row.id): _evaluated_fingerprint(indexed_geometry_mesh_scp_obj(objects, row.id), graph)
            for row in root.af_scp_system.scps}


def _evaluated_fingerprint(obj, depsgraph):
    if obj is None: return None
    evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh()
    if mesh is None: return None
    try:
        values = np.empty(len(mesh.vertices) * 3, dtype=np.float64); mesh.vertices.foreach_get("co", values)
        return len(mesh.vertices), sha256(values.tobytes()).hexdigest()
    finally: evaluated.to_mesh_clear()


def _install_sparse_stencils():
    from anthroforge.core.scp_runtime.attachment_wave_capture import _WaveCapture
    original = _WaveCapture.capture
    _WaveCapture.capture = lambda self, fibers: _sparse_capture(self, fibers, original)
    _WaveCapture._surface_snapshot = _sparse_surface_snapshot


def _sparse_capture(builder, fibers, original):
    builder._sparse_fibers = tuple(fibers); builder._sparse_maps = {}
    outcome = original(builder, fibers); request = outcome.request
    scp_ops = tuple(_remap_scp_op(builder, request, row) for row in request.scp_operations)
    fiber_ops = tuple(_remap_fiber_op(builder, request, row) for row in request.fiber_operations)
    return replace(outcome, request=replace(request, scp_operations=scp_ops, fiber_operations=fiber_ops))


def _sparse_surface_snapshot(builder, sid):
    from anthroforge.core.scp_runtime import attachment_wave_capture as capture
    from anthroforge.core.scp_runtime.common import indexed_geometry_mesh_scp_obj
    obj = indexed_geometry_mesh_scp_obj(builder.objects, sid); owner = builder._transform_object(sid)
    if obj is None or owner is None or builder.depsgraph is None: return None
    vertices, mapping = _sparse_vertices(obj, builder.depsgraph, _required_indices(builder, sid))
    builder._sparse_maps[str(sid)] = mapping; evaluated = obj.evaluated_get(builder.depsgraph)
    relative = owner.matrix_world.inverted_safe() @ evaluated.matrix_world
    rotation = owner.matrix_world.to_quaternion().inverted() @ evaluated.matrix_world.to_quaternion()
    generation = capture._current_generation(obj) + (len(vertices), 0)
    return capture.AttachmentSurfaceSnapshot(sid, builder.lookup[sid], vertices,
        np.empty((0, 3), dtype=np.int64), capture._matrix4(relative),
        capture._matrix3(rotation.to_matrix()), generation)


def _sparse_vertices(obj, depsgraph, indices):
    evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh()
    if mesh is None: return np.empty((0, 3)), {}
    try:
        valid = tuple(index for index in sorted(indices) if 0 <= index < len(mesh.vertices))
        values = np.asarray([tuple(mesh.vertices[index].co) for index in valid], dtype=np.float64)
        return np.ascontiguousarray(values).reshape((-1, 3)), {value: index for index, value in enumerate(valid)}
    finally: evaluated.to_mesh_clear()


def _required_indices(builder, sid):
    from anthroforge.core.scp_runtime.parent_anchor import stored_parent_binding
    from anthroforge.core.scp_runtime.runtime_state import attach_flow_param
    values = set()
    for child in builder.scps.values():
        if str(getattr(child, "parent_id", "")) != str(sid): continue
        _collect_param_indices(values, stored_parent_binding(child).get("param", {}))
        _collect_param_indices(values, attach_flow_param(child) or {})
    for fiber in builder._sparse_fibers: _collect_fiber_indices(values, fiber, sid)
    return values


def _collect_fiber_indices(values, fiber, sid):
    from anthroforge.core.attachment_codec import fiber_surface_param
    from anthroforge.core.vcp.fiber_node_attachment_codec import decode_node_attachments
    payload = decode_node_attachments(getattr(fiber, "node_attachments_json", ""))
    for node in () if payload is None else payload.nodes:
        if str(node.target_id) == str(sid): _collect_param_indices(values, fiber_surface_param(node.attach_raw) or {})


def _collect_param_indices(values, param):
    values.update(int(index) for index in dict(param or {}).get("tri_vidx", ()) if int(index) >= 0)


def _remap_scp_op(builder, request, operation):
    mapping = _operation_map(builder, request, operation.surface_index)
    return replace(operation, triangle=_mapped_triangle(mapping, operation.triangle),
                   flow_triangle=_mapped_triangle(mapping, operation.flow_triangle))


def _remap_fiber_op(builder, request, operation):
    mapping = _operation_map(builder, request, operation.surface_index)
    return replace(operation, triangle=_mapped_triangle(mapping, operation.triangle))


def _operation_map(builder, request, surface_index):
    if surface_index < 0: return {}
    return builder._sparse_maps.get(str(request.surfaces[surface_index].target_id), {})


def _mapped_triangle(mapping, triangle):
    return tuple(mapping.get(int(index), -1) if int(index) >= 0 else -1 for index in triangle)


def _handle_positions(root):
    values = {}
    for obj in bpy.context.scene.objects:
        key = _handle_key(obj, root.name)
        if key: values[key] = tuple(float(value) for value in obj.matrix_world.translation)
    return values


def _handle_key(obj, root_name):
    if str(obj.get("af_root_name", "")) != str(root_name): return ""
    fid = str(obj.get("af_fiber_id", ""))
    if obj.get("af_fiber_endpoint_handle"): return f"{fid}:E:{obj.get('af_fiber_endpoint')}"
    if obj.get("af_fiber_touch_handle"): return f"{fid}:T:{obj.get('af_fiber_touch_index')}"
    if obj.get("af_fiber_loop_anchor_handle"): return f"{fid}:L:{obj.get('af_fiber_loop_anchor_index')}"
    return ""


def _mesh_signatures(root):
    return {obj.name: _mesh_signature(obj) for obj in bpy.context.scene.objects
            if str(obj.get("af_root_name", "")) == str(root.name) and _output_mesh(obj)}


def _output_mesh(obj):
    return bool(obj.get("af_muscle_proxy") or obj.get("af_muscle_mirror_proxy") or
                obj.get("af_fiber_mirror_proxy")) and getattr(obj, "type", "") == "MESH"


def _mesh_signature(obj):
    mesh = obj.data; values = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", values); rounded = np.round(values, 7)
    return (len(mesh.vertices), len(mesh.polygons), sha256(rounded.tobytes()).hexdigest())


def _event(root, shortcut, value):
    event = bench._event(root, shortcut, value)
    event["handles"] = _handle_positions(root); event["meshes"] = _mesh_signatures(root)
    return event


def _events(root, shortcut, values):
    return tuple(_event(root, shortcut, float(value)) for value in values.split(","))


def _profiled_events(root, shortcut, values):
    profiler = cProfile.Profile(); profiler.enable()
    events = _events(root, shortcut, values); profiler.disable()
    output = io.StringIO()
    pstats.Stats(profiler, stream=output).sort_stats("cumulative").print_stats(80)
    return events, output.getvalue()


def _run(args):
    from anthroforge.core.deps.runtime_trace import clear_request_telemetry, set_request_telemetry
    root = bench._root(); initial, matrices = bench._points(root), bench._matrices(root)
    shortcut = next(row for row in root.af_shortcut_system.shortcuts if row.name == "Cranium Lobe Width")
    clear_request_telemetry(); set_request_telemetry(True)
    before = _geometry_fingerprints(root) if args.variant == "CLASSIFY" else {}
    events, profile = _profiled_events(root, shortcut, args.values) if args.variant == "PROFILE" else (_events(root, shortcut, args.values), "")
    result = bench._result(args, root, initial, matrices, events)
    if profile: result["profile"] = profile
    if before: result["geometry_changes"] = _geometry_changes(before, _geometry_fingerprints(root))
    if _STENCIL_STATS: result["stencil_stats"] = tuple(_STENCIL_STATS)
    result["variant"] = args.variant; return result


def _geometry_changes(before, after):
    return {key: before[key] != after.get(key) for key in before}


def main():
    args = _args(); source = bench._file_hash(args.file); bench._register()
    bpy.ops.wm.open_mainfile(filepath=args.file); _install(args.variant)
    args.mode = "native"; args.post_serial_check = False
    result = _run(args); result["source_unchanged"] = source == bench._file_hash(args.file)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("AF_ATTACHMENT_PROPAGATION_EXPERIMENT", args.variant, flush=True)


if __name__ == "__main__":
    main()
