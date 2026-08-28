"""Read-only and disposable-process profiling for AnthroForge Fiber workloads."""

import argparse
import cProfile
import hashlib
import io
import json
import os
import platform
import pstats
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import bpy


_ORIGINAL_OWNER_ZONE = None
_ORIGINAL_PUSH_OUT = None
_ORIGINAL_SEGMENT_VISIBLE = None
_ORIGINAL_SEGMENT_SAMPLES = None


def _base_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    modes = ("inventory", "solve", "sync", "profile", "property", "thickness-fast",
             "colliders", "cache-edit", "progressive", "geometry-stamp", "validate", "scale-collision",
             "progressive-equivalence",
             "property-burst", "handle-burst", "selection", "touch-batch", "hydration",
             "cache-lifecycle", "telemetry-overhead", "runtime-scenarios")
    parser.add_argument("--mode", choices=modes, default="inventory")
    parser.add_argument("--fiber", default="")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--bake", action="store_true")
    parser.add_argument("--top", type=int, default=35)
    parser.add_argument("--collider", default="")
    parser.add_argument("--events", type=int, default=20)
    return parser


def _add_solve_args(parser):
    parser.add_argument("--engine", choices=("V1", "V2", "V3"), default="V3")
    parser.add_argument("--nodes", type=int, default=0)
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--variant", choices=("baseline", "same-owner", "hoist-zones", "explicit-empty", "hoist-empty"), default="baseline")
    parser.add_argument("--ignore-prefer-bake", action="store_true")
    parser.add_argument("--include-points", action="store_true")
    parser.add_argument("--surface-routing", choices=("keep", "on", "off"), default="keep")
    parser.add_argument("--segment-collisions", choices=("keep", "on", "off"), default="keep")
    parser.add_argument("--warm-start", choices=("keep", "on", "off"), default="keep")
    parser.add_argument("--edit-field", choices=("bend_stiffness", "stretch_stiffness", "iterations_interactive", "use_segment_collisions"), default="bend_stiffness")
    return parser


def _args():
    parser = _add_solve_args(_base_parser())
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _register_addon():
    addons_dir = str(Path(__file__).resolve().parents[2])
    if addons_dir not in sys.path:
        sys.path.insert(0, addons_dir)
    import anthroforge
    anthroforge.register()
    return anthroforge


def _detach_fiber_handler():
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    sync = register_fiber_sync()
    handler = sync.on_depsgraph_update
    if handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(handler)
    return sync


def _load(path):
    _register_addon()
    _detach_fiber_handler()
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), load_ui=False)
    return _detach_fiber_handler()


def _root(scene):
    return next((obj for obj in scene.objects if obj.get("anthroforge_root")), None)


def _curve_points(obj):
    if obj is None or obj.type != "CURVE":
        return 0
    return sum(len(spline.points) + len(spline.bezier_points) for spline in obj.data.splines)


def _fiber_proxy(scene, root, fiber_id):
    return next((obj for obj in scene.objects if obj.get("af_fiber_proxy") and
                 not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name and
                 str(obj.get("af_fiber_id")) == str(fiber_id)), None)


def _runtime_metrics(fiber):
    from anthroforge.core.vcp import runtime_state as state
    return {"recompute_ms": state.fiber_recompute_ms(fiber),
            "status": state.fiber_recompute_status(fiber), "route": state.fiber_route_mode(fiber),
            "planner_ms": state.fiber_planner_ms(fiber), "refine_ms": state.fiber_refine_ms(fiber),
            "active_colliders": state.fiber_active_colliders(fiber), "eps_disp": state.fiber_eps_disp(fiber),
            "eps_pen": state.fiber_eps_pen(fiber), "not_converged": state.fiber_not_converged(fiber)}


def _fiber_record(scene, root, fiber):
    proxy = _fiber_proxy(scene, root, fiber.id)
    record = {"id": fiber.id, "name": fiber.name, "topology": fiber.topology_mode,
              "nodes": fiber.node_count, "interactive_iters": fiber.iterations_interactive,
              "bake_iters": fiber.iterations_bake, "touches": len(fiber.mid_touches),
              "loop_anchors": len(fiber.loop_anchors), "warm": fiber.use_warm_start}
    record.update({"surface_routing": fiber.use_surface_routing, "segment_collisions": fiber.use_segment_collisions,
                   "preview_route": fiber.preview_planner_route, "prefer_bake": bool(fiber.get("af_prefer_bake", False)),
                   "proxy_points": _curve_points(proxy), "muscle_id": fiber.muscle_id})
    record["parents"] = [fiber.a_parent_id, fiber.b_parent_id]
    record["runtime"] = _runtime_metrics(fiber)
    return record


def _mesh_record(obj):
    data = obj.data
    return {"name": obj.name, "scp_id": str(obj.get("af_scp_id", "")),
            "vertices": len(data.vertices), "edges": len(data.edges), "polygons": len(data.polygons),
            "modifiers": len(obj.modifiers), "hidden": bool(obj.hide_viewport),
            "scale": tuple(float(v) for v in obj.scale), "dimensions": tuple(float(v) for v in obj.dimensions),
            "matrix_determinant": float(obj.matrix_world.to_3x3().determinant())}


def _collider_records(scene, root):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    return [_mesh_record(obj) for obj in iter_geometry_mesh_scp_objects(scene, root.name)]


def _marker_counts(scene):
    names = ("af_fiber_proxy", "af_fiber_surface_proxy", "af_muscle_proxy", "af_blob_proxy",
             "af_soft_tissue_proxy", "af_fiber_endpoint_handle", "af_fiber_touch_handle")
    return {name: sum(bool(obj.get(name)) for obj in scene.objects) for name in names}


def _scene_record(scene):
    root = _root(scene)
    record = {"name": scene.name, "objects": len(scene.objects),
              "object_types": dict(Counter(obj.type for obj in scene.objects)), "markers": _marker_counts(scene)}
    if root is None:
        return record
    vcp = root.af_vcp_system
    colliders = _collider_records(scene, root)
    record.update({"root": root.name, "scps": len(root.af_scp_system.scps), "fibers": len(vcp.fibers),
                   "fiber_surfaces": len(vcp.fiber_surfaces), "muscles": len(vcp.muscles),
                   "blobs": len(vcp.blobs), "soft_tissues": len(vcp.soft_tissues)})
    record["fiber_records"] = [_fiber_record(scene, root, fiber) for fiber in vcp.fibers]
    record["colliders"] = colliders
    return record


def _inventory(path):
    started = time.perf_counter()
    _load(path)
    result = {"mode": "inventory", "file": str(Path(path).resolve()),
              "load_ms": (time.perf_counter() - started) * 1000.0,
              "data_objects": len(bpy.data.objects), "scenes": [_scene_record(s) for s in bpy.data.scenes]}
    return result


def _find_fibers(root, fiber_id):
    fibers = tuple(root.af_vcp_system.fibers)
    return tuple(f for f in fibers if not fiber_id or f.id == fiber_id or f.name == fiber_id)


def _solve_once(sync, root, scene, fiber, bake, include_points=False):
    from anthroforge.core.utils import depsgraph_for_scene
    started = time.perf_counter()
    points = sync._solver.solve_points(root, fiber, scene, depsgraph_for_scene(scene), bake=bake)
    result = {"wall_ms": (time.perf_counter() - started) * 1000.0, "points": len(points),
              "runtime": _runtime_metrics(fiber)}
    if include_points:
        result["coordinates"] = [[float(value) for value in point] for point in points]
    return result


def _set_optional_flag(fiber, name, value):
    if value != "keep":
        setattr(fiber, name, value == "on")


def _configure_fiber(fiber, args):
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        if args.nodes:
            fiber.node_count = args.nodes
        if args.iterations:
            setattr(fiber, "iterations_bake" if args.bake else "iterations_interactive", args.iterations)
        _set_optional_flag(fiber, "use_surface_routing", args.surface_routing)
        _set_optional_flag(fiber, "use_segment_collisions", args.segment_collisions)
        _set_optional_flag(fiber, "use_warm_start", args.warm_start)


def _solve(path, args):
    sync = _load(path)
    scene = bpy.context.scene
    root = _root(scene)
    _install_variant(args.variant)
    fibers = () if root is None else _find_fibers(root, args.fiber)
    rows = []
    for fiber in fibers:
        _configure_fiber(fiber, args)
        sync.clear_solver_cache(fiber.id)
        runs = [_solve_once(sync, root, scene, fiber, args.bake, args.include_points)
                for _ in range(max(1, args.repeat))]
        rows.append({"fiber": _fiber_record(scene, root, fiber), "runs": runs})
    return {"mode": "solve", "file": str(Path(path).resolve()), "bake": args.bake,
            "variant": args.variant, "rows": rows, "cache": _cache_stats(scene)}


def _timed_sync(sync, root, scene, target_ids):
    started = time.perf_counter()
    sync.sync_root_to_scene(root=root, scene=scene, target_fiber_ids=target_ids)
    return (time.perf_counter() - started) * 1000.0


def _sync(path, fiber_id, repeat, ignore_prefer):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fibers = _find_fibers(root, fiber_id)
    if ignore_prefer:
        for fiber in fibers:
            fiber["af_prefer_bake"] = False
    target_ids = None if not fiber_id else {fiber.id for fiber in fibers}
    sync.clear_solver_cache()
    runs = [_timed_sync(sync, root, scene, target_ids) for _ in range(max(1, repeat))]
    records = [_fiber_record(scene, root, fiber) for fiber in fibers]
    return {"mode": "sync", "runs_ms": runs, "fibers": records}


def _profile(path, fiber_id, bake, top):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = next(iter(_find_fibers(root, fiber_id)), None)
    profiler, stream = cProfile.Profile(), io.StringIO()
    profiler.enable()
    run = None if fiber is None else _solve_once(sync, root, scene, fiber, bake)
    profiler.disable()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(max(1, top))
    return {"mode": "profile", "fiber": None if fiber is None else fiber.id,
            "run": run, "profile": stream.getvalue()}


def _selected_fiber(root, fiber_id):
    return next(iter(_find_fibers(root, fiber_id)), None)


def _edit_value(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    return 0.95 if float(value) < 0.9 else 0.1


def _max_point_delta(first, second):
    from mathutils import Vector
    pairs = zip(first.get("coordinates", ()), second.get("coordinates", ()))
    return max(((Vector(a) - Vector(b)).length for a, b in pairs), default=0.0)


def _cache_edit(path, fiber_id, field):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, fiber_id)
    sync.clear_solver_cache(fiber.id)
    first = _solve_once(sync, root, scene, fiber, False, True)
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        setattr(fiber, field, _edit_value(getattr(fiber, field)))
    second = _solve_once(sync, root, scene, fiber, False, True)
    return {"mode": "cache-edit", "fiber": fiber.id, "field": field,
            "first": first, "second": second, "max_point_delta": _max_point_delta(first, second)}


def _property(path, fiber_id):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, fiber_id)
    started = time.perf_counter()
    if fiber is not None:
        fiber.thickness = float(fiber.thickness) + 1.0e-6
    elapsed = (time.perf_counter() - started) * 1000.0
    return {"mode": "property", "fiber": None if fiber is None else _fiber_record(scene, root, fiber),
            "wall_ms": elapsed}


def _thickness_fast(path, fiber_id):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, fiber_id)
    proxy = None if fiber is None else _fiber_proxy(scene, root, fiber.id)
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    started = time.perf_counter()
    with suppress_vcp_prop_updates():
        fiber.thickness = float(fiber.thickness) + 1.0e-6
    if proxy is not None:
        proxy.data.bevel_depth = max(0.0, float(fiber.thickness))
    return {"mode": "thickness-fast", "fiber": None if fiber is None else fiber.id,
            "wall_ms": (time.perf_counter() - started) * 1000.0}


def _materialize_record(collision, collider):
    started = time.perf_counter()
    surface = collision._collider_surface(collider)
    return {"id": collider["sid"], "name": collider["obj"].name,
            "wall_ms": (time.perf_counter() - started) * 1000.0,
            "vertices": 0 if surface is None else len(surface["verts_world"]),
            "triangles": 0 if surface is None else len(surface["triangles"])}


def _cache_stats(scene):
    from anthroforge.core import utils
    bucket = utils._SCENE_CACHE.get(int(scene.as_pointer()), {})
    keys = tuple(bucket)
    return {"entries": len(keys), "fiber_active": sum("fiber_active" in key for key in keys),
            "fiber_points": sum("fiber_points" in key for key in keys),
            "surface": sum("surface" in key for key in keys),
            "estimated_bytes": _deep_size(bucket), "key_bytes": _deep_size(keys)}


def _deep_size(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(_deep_size(k, seen) + _deep_size(v, seen) for k, v in value.items())
    if isinstance(value, (tuple, list, set, frozenset)):
        return size + sum(_deep_size(item, seen) for item in value)
    return size


def _percentile(values, fraction):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * float(fraction))))
    return ordered[index]


def _slice_summary(values, budget=12.0):
    return {"count": len(values), "total_ms": sum(values), "max_ms": max(values, default=0.0),
            "p50_ms": _percentile(values, 0.50), "p95_ms": _percentile(values, 0.95),
            "over_budget": sum(float(value) > float(budget) for value in values), "values_ms": values}


def _step_session(session, limit=10000):
    values, phases, result = [], [], session.result()
    while not result.done and len(values) < int(limit):
        started = time.perf_counter()
        result = session.step(12.0)
        values.append((time.perf_counter() - started) * 1000.0)
        phases.append(str(session.phase))
    return result, values, phases


def _progressive_once(sync, root, scene, fiber, include_points=False):
    from anthroforge.core.utils import depsgraph_for_scene
    from anthroforge.core.vcp.fiber_progressive import begin_fiber_solve
    sync.clear_solver_cache(fiber.id)
    started = time.perf_counter()
    session = begin_fiber_solve(sync._solver, root, fiber, scene, depsgraph_for_scene(scene))
    init_ms = (time.perf_counter() - started) * 1000.0
    result, slices, phases = _step_session(session)
    row = {"init_ms": init_ms, "slices": _slice_summary(slices), "done": result.done,
            "converged": result.converged, "stalled": result.stalled, "invalid": result.invalid_reason,
            "points": len(result.points), "planner_ms": result.planner_ms, "refine_ms": result.refine_ms,
            "max_disp": result.max_disp, "max_pen": result.max_pen, "active": result.active_count,
            "slice_phases": phases}
    if include_points:
        row["coordinates"] = [[float(value) for value in point] for point in result.points]
    return row


def _configure_progressive(fiber, args):
    _configure_fiber(fiber, args)
    if not args.iterations:
        return
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        fiber.iterations_bake = args.iterations


def _progressive(path, args):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    rows = []
    for fiber in _find_fibers(root, args.fiber):
        _configure_progressive(fiber, args)
        runs = [_progressive_once(sync, root, scene, fiber, args.include_points)
                for _ in range(max(1, args.repeat))]
        rows.append({"fiber": _fiber_record(scene, root, fiber), "runs": runs})
    return {"mode": "progressive", "file": str(Path(path).resolve()), "rows": rows,
            "cache": _cache_stats(scene)}


def _progressive_equivalence(path, args):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    rows = []
    for fiber in _find_fibers(root, args.fiber):
        _configure_progressive(fiber, args)
        rows.append(_equivalence_row(sync, root, scene, fiber))
    return {"mode": "progressive-equivalence", "file": str(Path(path).resolve()),
            "rows": rows}


def _equivalence_row(sync, root, scene, fiber):
    from anthroforge.core.utils import depsgraph_for_scene
    from anthroforge.core.vcp.fiber_progressive import begin_fiber_solve
    sync.clear_solver_cache(fiber.id)
    expected = sync._solver.solve_points(
        root, fiber, scene, depsgraph_for_scene(scene), bake=True)
    sync.clear_solver_cache(fiber.id)
    session = begin_fiber_solve(
        sync._solver, root, fiber, scene, depsgraph_for_scene(scene), "FINAL")
    actual, _slices, _phases = _step_session(session)
    return _point_comparison(fiber.id, expected, actual.points)


def _point_comparison(fiber_id, expected, actual):
    paired = tuple(zip(tuple(expected or ()), tuple(actual or ())))
    maximum = max(((left - right).length for left, right in paired), default=0.0)
    return {"fiber_id": fiber_id, "expected_count": len(expected),
            "actual_count": len(actual), "max_world_delta": maximum}


def _fast_owner_zone(self, nodes, oracle, colliders, params):
    owners = tuple(params.get("endpoint_owners", ("", "")) or ("", ""))
    if owners[0] and owners[0] == owners[1]:
        return self._same_owner_zone(owners[0], len(nodes))
    return _ORIGINAL_OWNER_ZONE(self, nodes, oracle, colliders, params)


def _hoisted_collision(self, nodes, pinned, oracle, colliders, params):
    max_pen = 0.0
    zones = self._owner_zone_limits(nodes, oracle, colliders, params)
    for index in range(1, len(nodes) - 1):
        if pinned[index]:
            continue
        cols = self._node_colliders(nodes, index, oracle, colliders, params, zones)
        nodes[index], pen = oracle.push_out_point(nodes[index], cols)
        max_pen = max(max_pen, pen)
    return max_pen


def _explicit_push_out(self, point, colliders=None):
    if colliders is not None and not tuple(colliders):
        return point.copy(), 0.0
    return _ORIGINAL_PUSH_OUT(self, point, colliders)


def _explicit_segment_visible(self, a, b, owners=(), colliders=None):
    if colliders is not None and not tuple(colliders):
        return True
    return _ORIGINAL_SEGMENT_VISIBLE(self, a, b, owners, colliders)


def _explicit_segment_samples(self, a, b, colliders=None):
    if colliders is not None and not tuple(colliders):
        return ()
    return _ORIGINAL_SEGMENT_SAMPLES(self, a, b, colliders)


def _install_owner_variant(solver_module, hoist):
    global _ORIGINAL_OWNER_ZONE
    cls = solver_module.FiberSolver
    _ORIGINAL_OWNER_ZONE = cls._owner_zone_limits
    cls._owner_zone_limits = _fast_owner_zone
    if hoist:
        cls._apply_collision_constraints = _hoisted_collision


def _install_empty_variant(collision_module):
    global _ORIGINAL_PUSH_OUT, _ORIGINAL_SEGMENT_VISIBLE, _ORIGINAL_SEGMENT_SAMPLES
    cls = collision_module.CollisionOracle
    _ORIGINAL_PUSH_OUT, _ORIGINAL_SEGMENT_VISIBLE = cls.push_out_point, cls.segment_visible
    _ORIGINAL_SEGMENT_SAMPLES = cls.segment_hit_samples
    cls.push_out_point, cls.segment_visible = _explicit_push_out, _explicit_segment_visible
    cls.segment_hit_samples = _explicit_segment_samples


def _install_variant(name):
    from anthroforge.core.vcp import fiber_collision, fiber_solver
    if name in ("same-owner", "hoist-zones", "hoist-empty"):
        _install_owner_variant(fiber_solver, name != "same-owner")
    if name in ("explicit-empty", "hoist-empty"):
        _install_empty_variant(fiber_collision)


def _colliders(path):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    from anthroforge.core.utils import depsgraph_for_scene
    from anthroforge.core.vcp import fiber_collision as collision
    started = time.perf_counter()
    oracle = collision.CollisionOracle(root, scene, depsgraph_for_scene(scene))
    colliders = oracle.colliders()
    bounds_ms = (time.perf_counter() - started) * 1000.0
    rows = [_materialize_record(collision, collider) for collider in colliders]
    return {"mode": "colliders", "bounds_ms": bounds_ms, "materialized": rows,
            "materialize_total_ms": sum(row["wall_ms"] for row in rows)}


def _find_collider(scene, root, token):
    from anthroforge.core.scp_runtime.common import iter_geometry_mesh_scp_objects
    objects = tuple(iter_geometry_mesh_scp_objects(scene, root.name))
    if not token:
        return next(iter(objects), None)
    return next((obj for obj in objects if obj.name == token or str(obj.get("af_scp_id", "")) == token), None)


def _payload_record(payload):
    verts = () if payload is None else payload.get("verts_world", ())
    bounds = None if payload is None else payload.get("bounds_world")
    return {"payload_id": 0 if payload is None else id(payload), "vertices": len(verts),
            "first_world": None if not verts else tuple(float(v) for v in verts[0]),
            "bounds": None if bounds is None else tuple(tuple(float(v) for v in point) for point in bounds)}


def _surface_record(obj, depsgraph):
    from anthroforge.core.scp_runtime.surface import _surface_stamp, build_mesh_surface_data
    evaluated = obj.evaluated_get(depsgraph)
    record = _payload_record(build_mesh_surface_data(obj, depsgraph))
    record["surface_stamp"] = _surface_stamp(obj, evaluated, depsgraph)
    return record


def _fresh_surface_record(obj, depsgraph):
    from anthroforge.core.scp_runtime.surface import _build_surface
    return _payload_record(_build_surface(obj, depsgraph))


def _set_first_vertex(obj, coordinate):
    obj.data.vertices[0].co = coordinate
    obj.data.update()
    bpy.context.view_layer.update()


def _point_delta(first, second):
    from mathutils import Vector
    if first is None or second is None:
        return 0.0
    return float((Vector(first) - Vector(second)).length)


def _geometry_comparison(before, after, fresh):
    cached_delta = _point_delta(before["first_world"], after["first_world"])
    fresh_delta = _point_delta(before["first_world"], fresh["first_world"])
    return {"collider_stamp_changed": before["collider_stamp"] != after["collider_stamp"],
            "surface_stamp_changed": before["surface_stamp"] != after["surface_stamp"],
            "cached_payload_reused": before["payload_id"] == after["payload_id"],
            "cached_vertex_delta": cached_delta, "fresh_vertex_delta": fresh_delta,
            "stale_cache_observed": fresh_delta > 1.0e-9 and cached_delta <= 1.0e-9}


def _mutated_geometry_record(obj, depsgraph):
    from anthroforge.core.vcp.fiber_collision import _collider_stamp
    original = obj.data.vertices[0].co.copy()
    before = _surface_record(obj, depsgraph)
    before["collider_stamp"] = _collider_stamp(obj)
    try:
        _set_first_vertex(obj, original + type(original)((0.001, 0.0, 0.0)))
        after, fresh = _surface_record(obj, depsgraph), _fresh_surface_record(obj, depsgraph)
        after["collider_stamp"] = _collider_stamp(obj)
    finally:
        _set_first_vertex(obj, original)
    return before, after, fresh


def _geometry_stamp(path, token):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    obj = None if root is None else _find_collider(scene, root, token)
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return {"mode": "geometry-stamp", "error": "Collider mesh not found."}
    from anthroforge.core.utils import depsgraph_for_scene
    before, after, fresh = _mutated_geometry_record(obj, depsgraph_for_scene(scene))
    return {"mode": "geometry-stamp", "object": _mesh_record(obj), "before": before,
            "after_cached": after, "after_forced_fresh": fresh,
            "comparison": _geometry_comparison(before, after, fresh), "saved": False}


def _validation_context(solver, root, scene, fiber, points, bake):
    from anthroforge.core.utils import depsgraph_for_scene
    from anthroforge.core.vcp.fiber_collision import CollisionOracle
    from anthroforge.core.vcp.fiber_modes import is_loop_fiber
    depsgraph, loop = depsgraph_for_scene(scene), is_loop_fiber(fiber)
    anchor_fn = solver._loop_anchors if loop else solver._open_anchors
    _runtime, anchors, issue = anchor_fn(root, scene, depsgraph, fiber)
    params = solver._runtime_params(fiber, bake)
    params = params if loop or issue else solver._with_endpoint_owners(params, anchors)
    params["segment_collisions"] = True
    oracle = CollisionOracle(root, scene, depsgraph, params["margin"], solver.surface_offset)
    active = solver._active_colliders(oracle, points, params["margin"])
    return loop, issue, anchors, params, oracle, active


def _actual_point_penetration(solver, points, loop, oracle, colliders, params):
    zones = solver._owner_zone_limits(points, oracle, colliders, params)
    start, end = (0, len(points)) if loop else (1, max(1, len(points) - 1))
    values = []
    for index in range(start, end):
        active = solver._node_colliders(points, index, oracle, colliders, params, zones)
        values.append(solver._sample_penetration(points[index], oracle, active))
    return max(values, default=0.0)


def _anchor_errors(anchors, points):
    values = [min(((anchor.point - point).length for point in points), default=1.0e9) for anchor in anchors]
    return {"max_anchor_error": max(values, default=0.0),
            "anchors_over_1e6": sum(value > 1.0e-6 for value in values), "anchor_errors": values}


def _validate_points(solver, root, scene, fiber, points, bake, stored):
    loop, issue, anchors, params, oracle, active = _validation_context(solver, root, scene, fiber, points, bake)
    if issue:
        return {"error": issue}
    seg_pen = solver._state_penetration(points, oracle, active, params, cyclic=loop, skip_ends=not loop)
    point_pen = _actual_point_penetration(solver, points, loop, oracle, active, params)
    result = {"stored_max_pen": stored["runtime"]["eps_pen"], "actual_segment_pen": seg_pen,
              "actual_interior_point_pen": point_pen, "active_colliders": len(active),
              "segments_clear": seg_pen <= 0.0, "stored_matches_actual": abs(seg_pen - stored["runtime"]["eps_pen"]) <= 1.0e-9}
    result.update(_anchor_errors(anchors, points))
    return result


def _validate(path, args):
    from mathutils import Vector
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    rows = []
    for fiber in _find_fibers(root, args.fiber):
        _configure_fiber(fiber, args)
        sync.clear_solver_cache(fiber.id)
        run = _solve_once(sync, root, scene, fiber, args.bake, True)
        points = [Vector(values) for values in run.pop("coordinates", ())]
        rows.append({"fiber": fiber.id, "solve": run,
                     "validation": _validate_points(sync._solver, root, scene, fiber, points, args.bake, run)})
    return {"mode": "validate", "file": str(Path(path).resolve()), "rows": rows,
            "cache": _cache_stats(scene)}


def _cube_collider(scale=0.1):
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    verts = [Vector((x, y, z)) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    matrix = Matrix.Diagonal((scale, scale, scale, 1.0))
    bounds = Vector((-0.5, -0.5, -0.5)) * scale, Vector((0.5, 0.5, 0.5)) * scale
    return {"surface": {}, "bvh": BVHTree.FromPolygons(verts, faces), "m": matrix,
            "m_inv": matrix.inverted(), "mn": bounds[0], "mx": bounds[1]}


def _scale_collision(path):
    _load(path)
    from mathutils import Vector
    from anthroforge.core.vcp.fiber_collision import _bvh_signed_distance, _nearest_push
    collider, margin = _cube_collider(0.1), 0.02
    outside = Vector((0.06, 0.0, 0.0))
    signed = _bvh_signed_distance(collider, outside)
    pushed, reported = _nearest_push(collider, Vector((0.04, 0.0, 0.0)), margin)
    return {"mode": "scale-collision", "scale": 0.1, "world_margin": margin,
            "outside_world_distance": 0.01, "reported_signed_distance": signed,
            "pushed_world_clearance": float(pushed.x - 0.05), "reported_penetration": reported,
            "expected_outside_penetration": 0.01, "expected_inside_penetration": 0.03}


def _telemetry_start(scene):
    from anthroforge.core.deps.runtime_trace import clear_request_telemetry, set_request_telemetry, set_runtime_trace
    from anthroforge.core.utils import scene_cache_set
    _reset_probe_runtime()
    set_runtime_trace(False)
    set_request_telemetry(True)
    clear_request_telemetry()
    scene_cache_set(scene, "af_perf_counters", {})


def _reset_probe_runtime():
    from anthroforge.core.visualization.fiber_refinement import shutdown_fiber_refinements
    from anthroforge.core.visualization.sync_runner import clear_pending_runtime
    clear_pending_runtime(keep_timer=False)
    shutdown_fiber_refinements(mark_unknown=False)


def _telemetry_result(scene):
    from anthroforge.core.deps.runtime_trace import request_telemetry
    from anthroforge.core.utils import scene_cache_get
    records = list(request_telemetry(clear=True))
    counters = dict(scene_cache_get(scene, "af_perf_counters") or {})
    return {"requests": records, "request_count": len(records), "counters": counters}


def _flush_pending_runtime():
    from anthroforge.core.visualization import sync_runner
    pending = len(sync_runner._PENDING)
    for item in sync_runner._PENDING:
        item.due_at = 0.0
    started = time.perf_counter()
    while sync_runner._PENDING:
        sync_runner._flush_pending()
    return pending, (time.perf_counter() - started) * 1000.0


def _drain_refinements(limit=100000):
    from anthroforge.core.visualization import fiber_refinement
    values, done = [], not fiber_refinement._QUEUE
    while not done and len(values) < int(limit):
        started = time.perf_counter()
        done = fiber_refinement.drain_fiber_refinements(max_slices=1)
        values.append((time.perf_counter() - started) * 1000.0)
    return {"done": done, "distribution": _slice_summary(values), "jobs": len(fiber_refinement._JOBS)}


def _property_event_times(fiber, count):
    base, values = float(fiber.bend_stiffness), []
    delta = -1.0e-5 if base >= 1.0 else 1.0e-5
    for index in range(max(1, int(count))):
        started = time.perf_counter()
        fiber.bend_stiffness = base + (delta if index % 2 == 0 else 0.0)
        values.append((time.perf_counter() - started) * 1000.0)
    return base, values


def _property_burst(path, args):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, args.fiber)
    if fiber is None:
        return {"mode": "property-burst", "error": "Fiber not found."}
    _telemetry_start(scene)
    original, values = _property_event_times(fiber, args.events)
    queued, flush_ms = _flush_pending_runtime()
    refinement = _drain_refinements()
    _restore_property(fiber, "bend_stiffness", original)
    return {"mode": "property-burst", "events": _slice_summary(values, 2.0), "queued": queued,
            "flush_ms": flush_ms, "refinement": refinement, "telemetry": _telemetry_result(scene)}


def _restore_property(owner, name, value):
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        setattr(owner, name, value)


def _fiber_handle(scene, fiber_id):
    return next((obj for obj in scene.objects if obj.get("af_fiber_endpoint_handle") and
                 str(obj.get("af_fiber_id", "")) == str(fiber_id)), None)


def _handle_events(root, scene, fiber, handle, count):
    from anthroforge.core.visualization.fiber_sync_runtime import _enqueue_fiber_runtime
    original, values = handle.location.copy(), []
    distance = .5 * max(float(getattr(fiber, "collision_radius", .002)), 1.0e-7)
    for index in range(max(1, int(count))):
        started = time.perf_counter()
        handle.location.x = original.x + distance * (index + 1) / max(1, int(count))
        _enqueue_fiber_runtime(root, scene, {fiber.id})
        values.append((time.perf_counter() - started) * 1000.0)
    return original, values


def _handle_burst(path, args):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, args.fiber)
    if fiber is None:
        return {"mode": "handle-burst", "error": "Fiber not found."}
    handle = _prepared_handle(sync, root, scene, fiber)
    if handle is None:
        return {"mode": "handle-burst", "error": "Fiber endpoint handle not found."}
    _telemetry_start(scene)
    original, values = _handle_events(root, scene, fiber, handle, args.events)
    queued, flush_ms = _flush_pending_runtime()
    refinement = _drain_refinements()
    result = _handle_result(values, queued, flush_ms, refinement, _telemetry_result(scene))
    handle.location = original
    return result


def _prepared_handle(sync, root, scene, fiber):
    _activate_fiber(root, fiber)
    _materialize_handles(sync, root, scene)
    return _fiber_handle(scene, fiber.id)


def _handle_result(values, queued, flush_ms, refinement, telemetry):
    return {"mode": "handle-burst", "events": _slice_summary(values, 5.0), "queued": queued,
            "flush_ms": flush_ms, "refinement": refinement, "telemetry": telemetry}


def _activate_fiber(root, fiber):
    root.af_vcp_system.active_vcp_type = "FIBER"
    root.af_vcp_system.active_vcp_id = fiber.id


def _materialize_handles(sync, root, scene):
    _select_fiber_proxy(scene, root)
    vis_col = sync._get_vis_collection(scene)
    sync._sync_handles(root, scene, vis_col, {})


def _select_fiber_proxy(scene, root):
    proxy = _fiber_proxy(scene, root, root.af_vcp_system.active_vcp_id)
    if proxy is not None:
        scene.view_layers[0].objects.active = proxy


def _selection_events(root, scene, fiber, count):
    from anthroforge.core.visualization.sync_runner import sync_from_dirty_hints
    values, hints = [], {"FIBER": {fiber.id}}
    for _index in range(max(1, int(count))):
        started = time.perf_counter()
        sync_from_dirty_hints(root, scene, hints, source="depsgraph", event_type="SELECTION",
                              full=False, dirty_aspects={"FIBER": {"SELECTION"}})
        values.append((time.perf_counter() - started) * 1000.0)
    return values


def _selection(path, args):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, args.fiber)
    if fiber is None:
        return {"mode": "selection", "error": "Fiber not found."}
    _telemetry_start(scene)
    values = _selection_events(root, scene, fiber, args.events)
    return {"mode": "selection", "events": _slice_summary(values, 5.0),
            "telemetry": _telemetry_result(scene)}


def _touch_fiber(root, fiber_id):
    selected = _selected_fiber(root, fiber_id)
    if selected is not None and selected.mid_touches:
        return selected
    return next((fiber for fiber in root.af_vcp_system.fibers if fiber.mid_touches), selected)


def _touch_updates(touch, count):
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    original = float(touch.normal_offset)
    with suppress_vcp_prop_updates():
        for index in range(max(1, int(count))):
            touch.normal_offset = original + (1.0e-6 if index % 2 == 0 else 0.0)
    return original


def _touch_batch(path, args):
    _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _touch_fiber(root, args.fiber)
    if fiber is None or not fiber.mid_touches:
        return {"mode": "touch-batch", "error": "Fiber with a touch was not found."}
    _telemetry_start(scene)
    original, started = _touch_updates(fiber.mid_touches[0], args.events), time.perf_counter()
    _schedule_attachment_update(root, scene, fiber.id)
    queue_call_ms = (time.perf_counter() - started) * 1000.0
    queued, flush_ms = _flush_pending_runtime()
    refinement = _drain_refinements()
    _restore_property(fiber.mid_touches[0], "normal_offset", original)
    return {"mode": "touch-batch", "touches": args.events, "queue_call_ms": queue_call_ms,
            "queued": queued, "flush_ms": flush_ms, "refinement": refinement, "telemetry": _telemetry_result(scene)}


def _schedule_attachment_update(root, scene, fiber_id):
    from anthroforge.core.visualization.sync_runner import schedule_sync_from_dirty_hints
    schedule_sync_from_dirty_hints(root, scene, {"FIBER": {fiber_id}}, source="operator",
                                   event_type="FIBER_UPDATE", full=False,
                                   dirty_aspects={"FIBER": {"ATTACHMENT"}}, quality="INTERACTIVE")


def _hydration(path, args):
    _register_addon()
    from anthroforge.core.deps.runtime_trace import clear_request_telemetry, set_request_telemetry, set_runtime_trace
    set_runtime_trace(False)
    set_request_telemetry(True)
    clear_request_telemetry()
    started = time.perf_counter()
    bpy.ops.wm.open_mainfile(filepath=str(Path(path).resolve()), load_ui=False)
    _detach_fiber_handler()
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    records = [] if root is None else [_fiber_record(scene, root, fiber) for fiber in _find_fibers(root, args.fiber)]
    return {"mode": "hydration", "load_ms": (time.perf_counter() - started) * 1000.0,
            "fibers": records, "telemetry": _telemetry_result(scene)}


def _cache_lifecycle(path, args):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, args.fiber)
    if fiber is None:
        return {"mode": "cache-lifecycle", "error": "Fiber not found."}
    from anthroforge.core.visualization.fiber_cache_lifecycle import invalidate_fiber_caches
    sync.clear_solver_cache(fiber.id)
    cold = _solve_once(sync, root, scene, fiber, args.bake)
    warm = _solve_once(sync, root, scene, fiber, args.bake)
    before, started = _cache_stats(scene), time.perf_counter()
    invalidate_fiber_caches(scene, root, {fiber.id})
    invalidation_ms, cleared = (time.perf_counter() - started) * 1000.0, _cache_stats(scene)
    after = _solve_once(sync, root, scene, fiber, args.bake)
    return {"mode": "cache-lifecycle", "cold": cold, "warm": warm, "after_invalidate": after,
            "before": before, "cleared": cleared, "invalidation_ms": invalidation_ms}


def _telemetry_solve_once(sync, root, scene, fiber, enabled):
    from anthroforge.app.runtime_requests import runtime_request
    from anthroforge.core.deps.runtime_trace import begin_request_telemetry, finish_request_telemetry, set_request_telemetry
    set_request_telemetry(enabled)
    sync.clear_solver_cache(fiber.id)
    request = runtime_request({"FIBER": {fiber.id}}, full=False, source="probe", event_type="FIBER_UPDATE")
    record = begin_request_telemetry(request, root=root, scene=scene)
    run = _solve_once(sync, root, scene, fiber, False)
    finish_request_telemetry(record, run["wall_ms"])
    return run["wall_ms"]


def _telemetry_overhead(path, args):
    sync = _load(path)
    scene, root = bpy.context.scene, _root(bpy.context.scene)
    fiber = _selected_fiber(root, args.fiber)
    if fiber is None:
        return {"mode": "telemetry-overhead", "error": "Fiber not found."}
    _telemetry_solve_once(sync, root, scene, fiber, False)
    pairs = [_telemetry_pair(sync, root, scene, fiber, index)
             for index in range(max(1, args.repeat))]
    baseline, enabled = [row[0] for row in pairs], [row[1] for row in pairs]
    base_median, enabled_median = _percentile(baseline, 0.5), _percentile(enabled, 0.5)
    overhead = 0.0 if base_median <= 0.0 else 100.0 * (enabled_median / base_median - 1.0)
    return {"mode": "telemetry-overhead", "baseline_ms": baseline, "enabled_ms": enabled,
            "baseline_median_ms": base_median, "enabled_median_ms": enabled_median, "overhead_percent": overhead}


def _telemetry_pair(sync, root, scene, fiber, index):
    order = (False, True) if index % 2 == 0 else (True, False)
    values = {enabled: _telemetry_solve_once(sync, root, scene, fiber, enabled)
              for enabled in order}
    return values[False], values[True]


def _runtime_scenarios(path, args):
    calls = {"property_burst": _property_burst, "handle_burst": _handle_burst,
             "selection": _selection, "touch_batch": _touch_batch,
             "hydration": _hydration, "cache_lifecycle": _cache_lifecycle}
    rows = {name: fn(path, args) for name, fn in calls.items()}
    return {"mode": "runtime-scenarios", "rows": rows}


def _run(args):
    return _probe_calls(args)[args.mode]()


def _probe_calls(args):
    path = args.blend
    return {"inventory": lambda: _inventory(path), "solve": lambda: _solve(path, args),
            "sync": lambda: _sync(path, args.fiber, args.repeat, args.ignore_prefer_bake),
            "profile": lambda: _profile(path, args.fiber, args.bake, args.top),
            "property": lambda: _property(path, args.fiber), "thickness-fast": lambda: _thickness_fast(path, args.fiber),
            "colliders": lambda: _colliders(path), "cache-edit": lambda: _cache_edit(path, args.fiber, args.edit_field),
            "progressive": lambda: _progressive(path, args), "geometry-stamp": lambda: _geometry_stamp(path, args.collider),
            "progressive-equivalence": lambda: _progressive_equivalence(path, args),
            "validate": lambda: _validate(path, args), "scale-collision": lambda: _scale_collision(path),
            "property-burst": lambda: _property_burst(path, args), "handle-burst": lambda: _handle_burst(path, args),
            "selection": lambda: _selection(path, args), "touch-batch": lambda: _touch_batch(path, args),
            "hydration": lambda: _hydration(path, args), "cache-lifecycle": lambda: _cache_lifecycle(path, args),
            "telemetry-overhead": lambda: _telemetry_overhead(path, args),
            "runtime-scenarios": lambda: _runtime_scenarios(path, args)}


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit():
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=5, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _build_value(name):
    value = getattr(bpy.app, name, "")
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value or "")


def _probe_metadata(args):
    background = bool(getattr(bpy.app, "background", False))
    return {"os": platform.platform(), "cpu": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", ""),
            "machine": platform.machine(), "python": platform.python_version(),
            "blender": str(getattr(bpy.app, "version_string", "")), "blender_build_hash": _build_value("build_hash"),
            "commit": _git_commit(), "arguments": vars(args), "background": background,
            "execution": "background" if background else "foreground",
            "blend_sha256": _file_sha256(args.blend), "blend_bytes": Path(args.blend).stat().st_size}


def _main():
    args = _args()
    os.environ["AF_FIBER_ENGINE"] = args.engine
    result = _run(args)
    result["benchmark_metadata"] = _probe_metadata(args)
    print("AF_PROBE_JSON=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    _main()
