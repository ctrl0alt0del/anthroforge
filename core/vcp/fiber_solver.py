from collections import OrderedDict
from math import isfinite
from time import perf_counter

from mathutils import Vector

from ..attachment_codec import fiber_surface_param
from ..deps.runtime_trace import telemetry_count
from ..visualization.fiber_sync_helpers import endpoint_world as resolve_fiber_endpoint_world, touch_world as resolve_fiber_touch_world
from .attachment_backend import attachment_issue, attachment_runtime
from .fiber_collision import CollisionOracle
from .fiber_ccd_bridge import native_ccd_enabled, native_collision_free_step
from .fiber_loop import loop_pin_targets, resample_closed
from .fiber_modes import is_loop_fiber, loop_anchor_specs
from .fiber_planner import DIRECT, LOCAL_FALLBACK, PlannerAnchor, plan_route
from .fiber_solver_v2 import CYCLIC, OPEN, StaticFiberSettings, clear_factor_cache, solve_static_fiber
from .fiber_symmetry import expand_fiber_loop_points, is_mirror_seam_loop
from .runtime_state import (
    fiber_recompute_status,
    set_fiber_active_colliders,
    set_fiber_eps_disp,
    set_fiber_eps_pen,
    set_fiber_invalid_reason,
    set_fiber_not_converged,
    set_fiber_planner_ms,
    set_fiber_recompute_status,
    set_fiber_refine_ms,
    set_fiber_route_mode,
)

_SURFACE_ROUTE_MAX_LENGTH_RATIO = 1.5
_SURFACE_ROUTE_MAX_DEVIATION_RATIO = 0.5
_SURFACE_ROUTE_EPS = 1.0e-8
_FIBER_CACHE_SCHEMA = 3
_FIBER_CACHE_LIMIT = 256


def _rounded_param(value):
    return round(float(value), 8) if isinstance(value, float) else value


class FiberSolver:
    """
    Minimum-length fiber solver with hard anchor constraints:
    - pinned endpoints
    - pinned ordered mid touch points
    - iterative length shortening
    - collision push-out against SCP proxy meshes
    - optional warm start (cached nodes)
    """

    def __init__(self, surface_offset=0.002):
        self.surface_offset = float(surface_offset)
        self._warm_cache = OrderedDict()
        self._cache = self._warm_cache
        self._loop_exact_results = OrderedDict()
        self._loop_cache_signatures = {}

    def clear_cache(self, fiber_id=None):
        clear_factor_cache()
        if fiber_id is None:
            self._warm_cache.clear()
            self._loop_exact_results.clear()
            self._loop_cache_signatures.clear()
        else:
            self._clear_fiber_cache(self._warm_cache, fiber_id)
            self._clear_fiber_cache(self._loop_exact_results, fiber_id)
            self._clear_fiber_cache(self._loop_cache_signatures, fiber_id)

    def _clear_fiber_cache(self, cache, fiber_id):
        target = str(fiber_id or "")
        for key in tuple(cache):
            if key == target or (isinstance(key, tuple) and key[-1] == target):
                cache.pop(key, None)

    def _fiber_cache_key(self, fiber_prop):
        try:
            identity = int(fiber_prop.as_pointer())
        except Exception:
            identity = id(fiber_prop)
        return identity, str(getattr(fiber_prop, "id", "") or "")

    def _attach_cache_signature(self, root, scene, fiber, anchors, params, oracle, quality, loop):
        params["_cache_signature"] = self._solve_cache_signature(
            root, scene, fiber, anchors, params, oracle, quality, loop)

    def _solve_cache_signature(self, root, scene, fiber, anchors, params, oracle, quality, loop):
        identities = self._runtime_identity(scene), self._runtime_identity(root)
        anchors = tuple(self._anchor_signature(anchor) for anchor in tuple(anchors or ()))
        colliders = tuple((row["sid"], row["stamp"]) for row in oracle.colliders())
        return (_FIBER_CACHE_SCHEMA, identities, "LOOP" if loop else "OPEN",
                str(quality), self._cache_settings(params), self._fiber_policy(fiber),
                anchors, colliders)

    def _cache_settings(self, params):
        fields = ("node_count", "iterations", "shorten_strength", "bend_strength",
                  "margin", "segment_collisions", "solver_version", "eps_disp", "eps_pen")
        return tuple((name, _rounded_param(params.get(name))) for name in fields)

    def _fiber_policy(self, fiber):
        fields = ("topology_mode", "symmetry_mode", "symmetry_axis",
                  "use_surface_routing", "preview_planner_route")
        values = tuple(str(getattr(fiber, name, "") or "") for name in fields)
        origin = tuple(round(float(value), 8) for value in getattr(fiber, "symmetry_origin", ()))
        return values, origin

    def _runtime_identity(self, value):
        uid = int(getattr(value, "session_uid", 0) or 0)
        if uid:
            return uid
        try:
            return int(value.as_pointer())
        except Exception:
            return id(value)

    def _default_margin(self):
        return 0.002

    def _runtime_params(self, fiber_prop, bake):
        node_count = max(8, int(fiber_prop.node_count))
        iterations = int(fiber_prop.iterations_bake if bake else fiber_prop.iterations_interactive)
        iterations = max(1, iterations)
        params = self._base_params(fiber_prop, node_count, iterations)
        params["min_iters"] = min(iterations, max(1, iterations // 4))
        return params

    def _base_params(self, fiber_prop, node_count, iterations):
        shorten, bend = self._strengths(fiber_prop)
        return {
            "node_count": node_count, "iterations": iterations, "margin": self._collision_radius(fiber_prop), "shorten_strength": shorten,
            "bend_strength": bend, "segment_collisions": bool(getattr(fiber_prop, "use_segment_collisions", False)), "eps_disp": 1e-5, "eps_pen": 1e-5,
            "solver_version": 1,
        }

    def _collision_radius(self, fiber_prop):
        value = getattr(fiber_prop, "collision_radius", self._default_margin())
        return max(0.0, float(value))

    def _strengths(self, fiber_prop):
        shorten = max(0.0, min(1.0, float(getattr(fiber_prop, "stretch_stiffness", 0.9))))
        bend = max(0.0, min(1.0, float(getattr(fiber_prop, "bend_stiffness", 0.15))))
        return shorten, bend

    def _initialize_nodes(self, fiber_prop, nodes_init, pin_targets, node_count):
        nodes = self._seed_or_cache_nodes(fiber_prop, nodes_init, node_count, None)
        pinned = [False] * node_count
        for idx, pt in pin_targets.items():
            nodes[idx] = pt.copy()
        for idx in pin_targets.keys():
            pinned[idx] = True
        return nodes, pinned

    def _seed_or_cache_nodes(self, fiber_prop, nodes_init, node_count, seed, signature=None):
        if seed is not None:
            return [p.copy() for p in seed]
        cached = self._warm_start_nodes(fiber_prop, node_count, signature)
        return [p.copy() for p in nodes_init] if cached is None else cached

    def _warm_start_nodes(self, fiber_prop, node_count, signature=None):
        key = self._fiber_cache_key(fiber_prop)
        enabled = bool(getattr(fiber_prop, "use_warm_start", False))
        compatible = signature is not None and self._loop_cache_signatures.get(key) == signature
        cached = self._warm_cache.get(key) if enabled and compatible else None
        return None if not cached else self._resample_polyline(cached, node_count)

    def _store_warm_cache(self, fiber_prop, points, signature):
        if signature is None or not points:
            return
        key = self._fiber_cache_key(fiber_prop)
        self._warm_cache[key] = [point.copy() for point in points]
        self._warm_cache.move_to_end(key)
        self._loop_cache_signatures[key] = signature
        self._trim_warm_cache()

    def _trim_warm_cache(self):
        while len(self._warm_cache) > _FIBER_CACHE_LIMIT:
            key, _points = self._warm_cache.popitem(last=False)
            self._loop_cache_signatures.pop(key, None)

    def _resample_nodes(self, src, count):
        if not src or count <= 0:
            return []
        if len(src) == count:
            return [p.copy() for p in src]
        last = len(src) - 1
        if last <= 0:
            return [src[0].copy() for _ in range(count)]
        return [self._resample_node(src, count, i, last) for i in range(count)]

    def _resample_node(self, src, count, index, last):
        t = 0.0 if count <= 1 else index * last / float(count - 1)
        i0 = min(last - 1, int(t))
        return src[-1].copy() if i0 >= last else src[i0].lerp(src[i0 + 1], t - i0)

    def _solver_iteration(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guard_targets=None, next_guards=None):
        pins = self._effective_pinned(pinned, guard_targets, len(nodes))
        targets = self._effective_pin_targets(pin_targets, guard_targets)
        self._apply_open_smoothing(nodes, pins, targets, params, it)
        max_pen = self._apply_collision_constraints(nodes=nodes, pinned=pins, oracle=oracle, colliders=colliders, params=params)
        max_pen = self._apply_segment_penalties(max_pen, nodes, pins, oracle, colliders, params)
        if self._uses_v2(params):
            max_pen = max(max_pen, self._apply_collision_constraints(nodes, pins, oracle, colliders, params))
        else:
            self._rollback_segment_introductions(nodes, prev_nodes, pins, oracle, colliders, params, next_guards=next_guards)
        self._restore_pins(nodes, targets)
        return self._max_displacement(nodes, prev_nodes), max_pen

    def _effective_pinned(self, pinned, guard_targets, count):
        if not guard_targets:
            return pinned
        if isinstance(pinned, set):
            return set(pinned) | set(guard_targets)
        out = list(pinned)
        for index in guard_targets:
            idx = int(index)
            if 0 <= idx < count:
                out[idx] = True
        return out

    def _effective_pin_targets(self, pin_targets, guard_targets):
        if not guard_targets:
            return pin_targets
        out = {int(i): p.copy() for i, p in dict(pin_targets or {}).items()}
        out.update({int(i): p.copy() for i, p in dict(guard_targets or {}).items()})
        return out

    def _restore_pins(self, nodes, pin_targets):
        for idx, pt in pin_targets.items():
            nodes[idx] = pt.copy()

    def solve_points(self, root, fiber_prop, scene, depsgraph, bake=False):
        from .free_path import require_controlled
        require_controlled(fiber_prop)
        from .fiber_progressive import begin_fiber_solve
        quality = "FINAL" if bake else "INTERACTIVE"
        session = begin_fiber_solve(self, root, fiber_prop, scene, depsgraph, quality)
        while not session.done:
            session.step(1.0e9)
        return session.result().points

    def _solve_open_fiber(self, root, fiber_prop, scene, depsgraph, bake):
        _runtime, anchors, issue = self._open_anchors(root, scene, depsgraph, fiber_prop)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        params, oracle, issue = self._solver_context(
            root, scene, fiber_prop, anchors, depsgraph, bake, False)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        guides = self._planner_guides(fiber_prop, oracle, anchors)
        seed, mode, planner_ms, planned = self._plan_seed(fiber_prop, oracle, anchors, bake)
        if self._preview_planner_route(fiber_prop):
            return self._planner_preview_result(fiber_prop, seed, mode, planner_ms, planned)
        nodes, converged, max_disp, max_pen, active_count, refine_ms = self._refine_solve(fiber_prop, anchors, guides, oracle, params, seed)
        return self._complete_open(fiber_prop, nodes, converged, max_disp, max_pen,
                                   mode, planner_ms, refine_ms, active_count, planned, params)

    def _complete_open(self, fiber, nodes, converged, disp, pen, mode, planner_ms, refine_ms, active, planned, params):
        self._store_status(fiber, converged, disp, pen)
        self._store_metrics(fiber, mode, planner_ms, refine_ms, max(active, len(planned)))
        if converged:
            self._store_warm_cache(fiber, nodes, params.get("_cache_signature"))
        return nodes

    def _refine_solve(self, fiber_prop, anchors, guides, oracle, params, seed):
        t0 = perf_counter()
        nodes, converged, max_disp, max_pen, active_count = self._solve_multilevel(fiber_prop, anchors, guides, oracle, params, seed)
        return nodes, converged, max_disp, max_pen, active_count, (perf_counter() - t0) * 1000.0

    def _solve_solved_loop(self, root, fiber_prop, scene, depsgraph, bake):
        _runtime, anchors, issue = self._loop_anchors(root, scene, depsgraph, fiber_prop)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        params, oracle, issue = self._solver_context(
            root, scene, fiber_prop, anchors, depsgraph, bake, True)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        route, mode, planner_ms, planned = self._loop_seed_route(oracle, anchors, bake)
        nodes, converged, max_disp, max_pen, active_count, refine_ms = self._refine_loop(fiber_prop, anchors, oracle, params, route)
        self._store_status(fiber_prop, converged, max_disp, max_pen)
        if not self._preserve_metrics(fiber_prop, bake):
            self._store_metrics(fiber_prop, mode, planner_ms, refine_ms, max(active_count, len(planned)))
        if converged:
            self._store_warm_cache(fiber_prop, nodes, params.get("_cache_signature"))
        return nodes

    def _solver_context(self, root, scene, fiber, anchors, depsgraph, bake, loop):
        params = self._runtime_params(fiber, bake)
        issue = self._configuration_issue(anchors, params)
        if issue:
            return params, None, issue
        oracle = CollisionOracle(root, scene, depsgraph, params["margin"], self.surface_offset)
        quality = "FINAL" if bake else "INTERACTIVE"
        self._attach_cache_signature(root, scene, fiber, anchors, params, oracle, quality, loop)
        return params, oracle, ""

    def _configuration_issue(self, anchors, params):
        if len(tuple(anchors or ())) > int(params["node_count"]):
            return "Fiber has more hard anchors than output nodes."
        return ""

    def _loop_route_anchors(self, root, scene, runtime_registry, fiber_prop):
        pairs = loop_anchor_specs(fiber_prop)
        if len(pairs) < 3:
            return None
        anchors = [self._route_anchor(root, scene, runtime_registry, pid, raw) for pid, raw in pairs]
        return None if any(anchor is None for anchor in anchors) else self._expanded_loop_anchors(fiber_prop, anchors)

    def _expanded_loop_anchors(self, fiber_prop, anchors):
        if not is_mirror_seam_loop(fiber_prop):
            return anchors
        points = expand_fiber_loop_points(fiber_prop, [anchor.point for anchor in anchors])
        mirrored = self._mirrored_loop_anchors(fiber_prop, anchors, points[len(anchors):])
        return list(anchors) + mirrored

    def _mirrored_loop_anchors(self, fiber, anchors, points):
        from .fiber_symmetry import signed_distance, mirror_axis, mirror_origin
        axis, origin = mirror_axis(fiber), mirror_origin(fiber)
        seam = len(anchors) > 1 and all(abs(signed_distance(row.point, axis, origin)) <= 1.0e-5
                                      for row in (anchors[0], anchors[-1]))
        sources = anchors[1:-1] if seam else anchors
        return [PlannerAnchor(point.copy(), source.owner_id)
                for point, source in zip(points, reversed(sources))]

    def _loop_seed_route(self, oracle, anchors, bake):
        _ = bake
        return self._local_loop_seed(oracle, anchors)

    def _local_loop_seed(self, oracle, anchors):
        points = [anchor.point.copy() for anchor in anchors]
        active = oracle.active_colliders_for_polyline(points, padding=max(0.05, oracle.margin * 4.0))
        return points, DIRECT, 0.0, tuple(c["sid"] for c in active)

    def _refine_loop(self, fiber_prop, anchors, oracle, params, route):
        t0 = perf_counter()
        nodes, converged, max_disp, max_pen, active_count = self._solve_loop_nodes(fiber_prop, anchors, oracle, params, route)
        return nodes, converged, max_disp, max_pen, active_count, (perf_counter() - t0) * 1000.0

    def _solve_loop_nodes(self, fiber_prop, anchors, oracle, params, route):
        sig = self._loop_cache_signature(anchors, params)
        route = route or [anchor.point.copy() for anchor in anchors]
        targets = loop_pin_targets(route, [anchor.point.copy() for anchor in anchors], params["node_count"])
        params = dict(params, pin_owners=self._pin_owners(anchors, targets))
        cached = self._cached_loop_result(fiber_prop, sig, params["node_count"])
        if cached is not None:
            cached = self._validated_loop_cache(cached, targets, oracle, params)
            if cached[1]:
                return cached
            self._discard_loop_exact(fiber_prop)
        nodes = self._loop_nodes(fiber_prop, route, params["node_count"], sig)
        self._restore_pins(nodes, targets)
        active = self._active_colliders(oracle, nodes, params["margin"])
        converged, max_disp, max_pen = self._run_cyclic_iterations(nodes, targets, oracle, active, params)
        return nodes, converged, max_disp, max_pen, len(active)

    def _validated_loop_cache(self, cached, targets, oracle, params):
        points, converged, disp, _pen, active = cached
        self._restore_pins(points, targets)
        converged, disp, pen = self._finish_cyclic_state(
            points, oracle, params, converged, disp)
        return points, converged, disp, pen, active

    def _discard_loop_exact(self, fiber_prop):
        self._loop_exact_results.pop(self._fiber_cache_key(fiber_prop), None)

    def _cached_loop_result(self, fiber_prop, signature, count):
        if not bool(getattr(fiber_prop, "use_warm_start", False)):
            return None
        key = self._fiber_cache_key(fiber_prop)
        record = self._loop_exact_results.get(key)
        if record is None or record[0] != signature or len(record[1]) != int(count):
            return None
        points = [point.copy() for point in record[1]]
        return points, bool(record[2]), float(record[3]), float(record[4]), int(record[5])

    def _store_loop_exact_result(self, fiber_prop, signature, points, diagnostics):
        if signature is None or not bool(diagnostics[0]):
            return
        key = self._fiber_cache_key(fiber_prop)
        values = bool(diagnostics[0]), float(diagnostics[1]), float(diagnostics[2]), int(diagnostics[3])
        self._loop_exact_results[key] = (signature, [p.copy() for p in points], *values)
        self._loop_exact_results.move_to_end(key)
        while len(self._loop_exact_results) > _FIBER_CACHE_LIMIT:
            self._loop_exact_results.popitem(last=False)

    def _store_loop_cache_signature(self, fiber_prop, anchors, params):
        key = self._fiber_cache_key(fiber_prop)
        self._loop_cache_signatures[key] = self._loop_cache_signature(anchors, params)

    def _loop_cache_signature(self, anchors, params):
        if params.get("_cache_signature") is not None:
            return params["_cache_signature"]
        fields = ("node_count", "iterations", "shorten_strength", "bend_strength",
                  "margin", "segment_collisions", "solver_version")
        values = tuple((key, _rounded_param(params.get(key))) for key in fields)
        points = tuple(self._anchor_signature(anchor) for anchor in tuple(anchors or ()))
        return values, points

    def _anchor_signature(self, anchor):
        point = tuple(round(float(value), 8) for value in anchor.point)
        owner = str(getattr(anchor, "owner_id", "") or "")
        return owner, str(getattr(anchor, "attach_raw", "") or ""), point

    def _loop_nodes(self, fiber_prop, route, node_count, signature=None):
        cached = self._warm_loop_nodes(fiber_prop, node_count, signature)
        return resample_closed(route, node_count) if cached is None else cached

    def _warm_loop_nodes(self, fiber_prop, node_count, signature=None):
        key = self._fiber_cache_key(fiber_prop)
        enabled = bool(getattr(fiber_prop, "use_warm_start", False))
        compatible = signature is not None and self._loop_cache_signatures.get(key) == signature
        cached = self._warm_cache.get(key) if enabled and compatible else None
        return None if not cached else self._resample_loop_cache(cached, node_count)

    def _resample_loop_cache(self, cached, count):
        if len(cached) == int(count):
            return [p.copy() for p in cached]
        return resample_closed(cached, int(count))

    def _run_cyclic_iterations(self, nodes, pin_targets, oracle, colliders, params):
        prev_nodes, pinned = [p.copy() for p in nodes], set(pin_targets)
        safe = first_safe = self._safe_snapshot(nodes, oracle, colliders, params, cyclic=True, pinned=pinned)
        guards = {}
        for it in range(params["iterations"]):
            local = self._collision_context_params(params)
            colliders = self._active_colliders(oracle, nodes, params["margin"])
            next_guards = {}
            max_disp, max_pen, alpha = self._cyclic_step(nodes, prev_nodes, pinned, pin_targets, oracle, colliders, local, it, guards, next_guards)
            if self._blocked_clear(alpha, max_pen, local): break
            guards = next_guards if alpha >= 0.999999 else {}
            prev_nodes, colliders, safe = self._post_iteration_state(nodes, oracle, local, safe, cyclic=True, pinned=pinned)
            if self._iteration_converged(it, max_disp, max_pen, params):
                return self._finish_cyclic_state(nodes, oracle, params, True, max_disp)
        return self._restore_unconverged(nodes, safe, first_safe, oracle, colliders, params, max_disp, max_pen, cyclic=True)

    def _finish_cyclic_state(self, nodes, oracle, params, converged, max_disp):
        residual = self._final_residual(nodes, oracle, params, cyclic=True)
        return bool(converged and residual < params["eps_pen"]), max_disp, residual

    def _cyclic_step(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards):
        telemetry_count("fiber_iterations")
        _ = prev_nodes
        start = [p.copy() for p in nodes]
        candidate = [p.copy() for p in start]
        trial_disp, trial_pen = self._cyclic_iteration(candidate, start, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards)
        params["_v2_contact"] = self._uses_v2(params) and trial_pen > params["eps_pen"]
        alpha, pen = self._accept_candidate(nodes, start, candidate, oracle, params, cyclic=True)
        return self._max_displacement(nodes, start), self._accepted_pen(alpha, pen, trial_pen), alpha

    def _cyclic_iteration(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guard_targets=None, next_guards=None):
        pins = self._effective_pinned(pinned, guard_targets, len(nodes))
        targets = self._effective_pin_targets(pin_targets, guard_targets)
        self._apply_cyclic_smoothing(nodes, pins, targets, params, it)
        max_pen = self._apply_cyclic_collision_constraints(nodes, pins, oracle, colliders, params)
        max_pen = self._apply_segment_penalties(max_pen, nodes, pins, oracle, colliders, params, cyclic=True)
        if self._uses_v2(params):
            max_pen = max(max_pen, self._apply_cyclic_collision_constraints(nodes, pins, oracle, colliders, params))
        else:
            self._rollback_segment_introductions(nodes, prev_nodes, pins, oracle, colliders, params, cyclic=True, next_guards=next_guards)
        self._restore_pins(nodes, targets)
        return self._max_displacement(nodes, prev_nodes), max_pen

    def _apply_open_smoothing(self, nodes, pinned, targets, params, it):
        if self._uses_v2(params):
            self._apply_v2_global_step(nodes, targets, params, False)
            return
        self._apply_length_shortening(nodes, pinned, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_bend_smoothing(nodes, pinned, params["bend_strength"])

    def _apply_cyclic_smoothing(self, nodes, pinned, targets, params, it):
        if self._uses_v2(params):
            self._apply_v2_global_step(nodes, targets, params, True)
            return
        self._apply_cyclic_shortening(nodes, pinned, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_cyclic_bend(nodes, pinned, params["bend_strength"])

    def _uses_v2(self, params):
        return int(params.get("solver_version", 1)) >= 2

    def _apply_v2_global_step(self, nodes, targets, params, cyclic):
        topology = CYCLIC if cyclic else OPEN
        settings = StaticFiberSettings(params["shorten_strength"], params["bend_strength"], 1.0, topology)
        result = solve_static_fiber(nodes, targets, settings)
        for index, point in enumerate(result.points):
            nodes[index] = Vector(point)

    def _apply_cyclic_shortening(self, nodes, pinned, strength):
        self._apply_cyclic_average(nodes, pinned, strength, additive=False)

    def _apply_cyclic_bend(self, nodes, pinned, strength):
        self._apply_cyclic_average(nodes, pinned, strength, additive=True)

    def _apply_cyclic_average(self, nodes, pinned, strength, additive):
        if len(nodes) < 3 or strength <= 0.0:
            return
        new_nodes = [p.copy() for p in nodes]
        for i in range(len(nodes)):
            if i not in pinned:
                new_nodes[i] = self._cyclic_target(nodes, i, strength, additive)
        self._commit_cyclic_nodes(nodes, new_nodes, pinned)

    def _cyclic_target(self, nodes, index, strength, additive):
        avg = (nodes[index - 1] + nodes[(index + 1) % len(nodes)]) * 0.5
        return nodes[index] + (avg - nodes[index]) * strength if additive else nodes[index].lerp(avg, strength)

    def _commit_cyclic_nodes(self, nodes, new_nodes, pinned):
        for i in range(len(nodes)):
            if i not in pinned:
                nodes[i] = new_nodes[i]

    def _apply_cyclic_collision_constraints(self, nodes, pinned, oracle, colliders, params):
        max_pen = 0.0
        zones = self._owner_zone_limits(nodes, oracle, colliders, params)
        for i in range(len(nodes)):
            if i in pinned:
                continue
            active = self._node_colliders(nodes, i, oracle, colliders, params, zones)
            nodes[i], pen = oracle.push_out_point(nodes[i], active)
            max_pen = max(max_pen, pen)
        return max_pen

    def _runtime_registry(self, scene, depsgraph):
        return attachment_runtime(scene, depsgraph)

    def _open_anchors(self, root, scene, depsgraph, fiber_prop):
        runtime = self._runtime_registry(scene, depsgraph)
        anchors = self._route_anchors(root, scene, runtime, fiber_prop)
        issue = "" if anchors is not None else self._open_attachment_issue(root, scene, runtime, fiber_prop)
        return runtime, anchors, issue

    def _loop_anchors(self, root, scene, depsgraph, fiber_prop):
        runtime = self._runtime_registry(scene, depsgraph)
        anchors = self._loop_route_anchors(root, scene, runtime, fiber_prop)
        issue = "" if anchors is not None else self._loop_attachment_issue(root, scene, runtime, fiber_prop)
        return runtime, anchors, issue

    def _invalid_result(self, fiber_prop, issue):
        self._mark_invalid(fiber_prop, issue)
        return []

    def _mark_failed(self, fiber_prop):
        set_fiber_not_converged(fiber_prop, True)
        set_fiber_eps_disp(fiber_prop, 0.0)
        set_fiber_eps_pen(fiber_prop, 0.0)
        self._store_metrics(fiber_prop, LOCAL_FALLBACK, 0.0, 0.0, 0)

    def _mark_invalid(self, fiber_prop, issue):
        set_fiber_invalid_reason(fiber_prop, str(issue or "Invalid attachment."))
        set_fiber_recompute_status(fiber_prop, "INVALID_ATTACHMENT")
        self._mark_failed(fiber_prop)

    def _clear_invalid_state(self, fiber_prop):
        set_fiber_invalid_reason(fiber_prop, "")
        if fiber_recompute_status(fiber_prop) == "INVALID_ATTACHMENT":
            set_fiber_recompute_status(fiber_prop, "UNKNOWN")

    def _open_attachment_issue(self, root, scene, runtime_registry, fiber_prop):
        specs = [(fiber_prop.a_parent_id, fiber_prop.a_attach_param), (fiber_prop.b_parent_id, fiber_prop.b_attach_param)]
        specs[1:1] = [(tp.parent_id, tp.attach_param) for tp in getattr(fiber_prop, "mid_touches", ())]
        return self._first_attachment_issue(root, scene, runtime_registry, specs)

    def _loop_attachment_issue(self, root, scene, runtime_registry, fiber_prop):
        return self._first_attachment_issue(root, scene, runtime_registry, loop_anchor_specs(fiber_prop))

    def _first_attachment_issue(self, root, scene, runtime_registry, specs):
        for parent_id, raw in tuple(specs or ()):
            issue = attachment_issue(root, scene, parent_id, raw, runtime_registry)
            if issue:
                return issue
        return "Invalid attachment payload."

    def _route_anchors(self, root, scene, runtime_registry, fiber_prop):
        from .shared_point_storage import endpoint_record
        anchors = [self._touch_anchor(root, scene, runtime_registry, endpoint_record(fiber_prop, "a"))]
        anchors.extend(self._touch_anchor(root, scene, runtime_registry, tp) for tp in getattr(fiber_prop, "mid_touches", ()))
        anchors.append(self._touch_anchor(root, scene, runtime_registry, endpoint_record(fiber_prop, "b")))
        return None if any(anchor is None for anchor in anchors) else anchors

    def _touch_anchor(self, root, scene, runtime_registry, touch):
        point = resolve_fiber_touch_world(root, scene, runtime_registry, touch)
        return None if point is None else PlannerAnchor(point.copy(), str(touch.parent_id or ""), str(touch.attach_param or ""))

    def _route_anchor(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        point = self._endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)
        return None if point is None else PlannerAnchor(point.copy(), str(parent_id or ""), str(attach_param_raw or ""))

    def _planner_guides(self, fiber_prop, oracle, anchors):
        if not self._use_surface_routing(fiber_prop):
            return []
        guides, last = [], max(0, len(anchors) - 2)
        for i in range(len(anchors) - 1):
            if not self._interior_segment(anchors, i):
                guides.extend(self._segment_guides(oracle, anchors[i], anchors[i + 1]))
            if i < last:
                guides.append(anchors[i + 1].point.copy())
        return guides

    def _interior_segment(self, anchors, index):
        return 0 < int(index) < len(tuple(anchors or ())) - 2

    def _use_surface_routing(self, fiber_prop):
        return bool(getattr(fiber_prop, "use_surface_routing", True))

    def _segment_guides(self, oracle, start, end):
        route = self._surface_route(oracle, start, end)
        return [] if route is None else [point.copy() for point in route[1:-1]]

    def _surface_route(self, oracle, start, end):
        route = self._surface_param_route(oracle, start, end)
        route = self._surface_vertex_route(oracle, start, end) if route is None else route
        if route is None:
            return None
        route = self._shortcut_surface_route(oracle, start, end, route)
        return route if self._surface_route_usable(route) else None

    def _surface_route_usable(self, route):
        if len(route) <= 2:
            return True
        direct = (route[-1] - route[0]).length
        if direct <= _SURFACE_ROUTE_EPS:
            return False
        length_ok = self._surface_route_ratio(route, direct) <= _SURFACE_ROUTE_MAX_LENGTH_RATIO
        deviation_ok = self._surface_route_deviation_ratio(route, direct) <= _SURFACE_ROUTE_MAX_DEVIATION_RATIO
        return bool(length_ok and deviation_ok)

    def _surface_route_ratio(self, route, direct):
        return self._polyline_length(route) / max(float(direct), _SURFACE_ROUTE_EPS)

    def _surface_route_deviation_ratio(self, route, direct):
        return self._max_chord_deviation(route) / max(float(direct), _SURFACE_ROUTE_EPS)

    def _polyline_length(self, points):
        return sum((points[i + 1] - points[i]).length for i in range(len(points) - 1))

    def _max_chord_deviation(self, route):
        start, chord = route[0], route[-1] - route[0]
        if chord.length_squared <= _SURFACE_ROUTE_EPS:
            return 0.0
        return max(self._point_chord_deviation(point, start, chord) for point in route[1:-1])

    def _point_chord_deviation(self, point, start, chord):
        t = (point - start).dot(chord) / chord.length_squared
        closest = start + chord * max(0.0, min(1.0, t))
        return (point - closest).length

    def _surface_param_route(self, oracle, start, end):
        params = self._surface_route_params(start, end)
        if params is not None and hasattr(oracle, "surface_param_path"):
            return oracle.surface_param_path(start.owner_id, params[0], params[1])
        return None

    def _surface_vertex_route(self, oracle, start, end):
        verts = self._surface_route_vertices(start, end)
        if verts is None:
            return None
        return oracle.surface_path(start.owner_id, verts[0], verts[1])

    def _surface_route_params(self, start, end):
        if not start.owner_id or start.owner_id != end.owner_id:
            return None
        params = fiber_surface_param(start.attach_raw), fiber_surface_param(end.attach_raw)
        return None if any(param is None for param in params) else params

    def _shortcut_surface_route(self, oracle, start, end, route):
        if len(route) <= 2 or not hasattr(oracle, "segment_visible"):
            return route
        active = self._surface_route_colliders(oracle, start, end)
        return self._surface_shortcut_walk(oracle, route, start.owner_id, active)

    def _surface_route_colliders(self, oracle, start, end):
        if not hasattr(oracle, "active_colliders_for_segment"):
            return None
        pad = max(0.05, getattr(oracle, "clearance", 0.0), getattr(oracle, "margin", 0.0) * 4.0)
        return oracle.active_colliders_for_segment(start.point, end.point, owners=(start.owner_id, end.owner_id), padding=pad)

    def _surface_shortcut_walk(self, oracle, route, owner_id, active):
        out, i = [route[0].copy()], 0
        while i < len(route) - 1:
            i = self._furthest_surface_visible(oracle, route, owner_id, active, i)
            out.append(route[i].copy())
        return out

    def _furthest_surface_visible(self, oracle, route, owner_id, active, index):
        for j in range(len(route) - 1, index, -1):
            if oracle.segment_visible(route[index], route[j], (owner_id, owner_id), active):
                return j
        return index + 1

    def _surface_route_vertices(self, start, end):
        if not start.owner_id or start.owner_id != end.owner_id:
            return None
        verts = self._anchor_vertex(start), self._anchor_vertex(end)
        return None if -1 in verts else verts

    def _anchor_vertex(self, anchor):
        param = fiber_surface_param(anchor.attach_raw)
        return -1 if param is None else self._param_vertex(param)

    def _param_vertex(self, param):
        tri = tuple(dict(param or {}).get("tri_vidx", ()))
        weights = tuple(dict(param or {}).get("tri_weights", ()))
        return self._weighted_vertex(tri, weights)

    def _weighted_vertex(self, tri, weights, eps=1.0e-6):
        for vidx, weight in zip(tuple(tri or ()), tuple(weights or ())):
            if abs(float(weight) - 1.0) <= eps:
                return int(vidx)
        return -1

    def _plan_seed(self, fiber_prop, oracle, anchors, bake):
        if not (bake or self._preview_planner_route(fiber_prop) or self._interactive_collision_plan(fiber_prop)):
            return None, LOCAL_FALLBACK, 0.0, ()
        t0 = perf_counter()
        result = plan_route(oracle, anchors, allow_dense=bool(bake))
        self._set_planned_colliders(oracle, result.active_ids)
        return result.points, result.mode, (perf_counter() - t0) * 1000.0, result.active_ids

    def _set_planned_colliders(self, oracle, collider_ids):
        if hasattr(oracle, "require_colliders"):
            oracle.require_colliders(collider_ids)

    def _interactive_collision_plan(self, fiber_prop):
        return bool(getattr(fiber_prop, "use_segment_collisions", False))

    def _preview_planner_route(self, fiber_prop):
        return bool(getattr(fiber_prop, "preview_planner_route", False))

    def _planner_preview_result(self, fiber_prop, seed, mode, planner_ms, planned):
        points = [] if seed is None else [p.copy() for p in seed]
        self._store_status(fiber_prop, True, 0.0, 0.0)
        self._store_metrics(fiber_prop, mode, planner_ms, 0.0, len(planned))
        return points

    def _store_metrics(self, fiber_prop, mode, planner_ms, refine_ms, active_count):
        set_fiber_route_mode(fiber_prop, mode)
        set_fiber_planner_ms(fiber_prop, planner_ms)
        set_fiber_refine_ms(fiber_prop, refine_ms)
        set_fiber_active_colliders(fiber_prop, active_count)

    def _preserve_metrics(self, fiber_prop, bake):
        _ = fiber_prop, bake
        return False

    def _solve_multilevel(self, fiber_prop, anchors, guide_worlds, oracle, params, seed):
        params = self._with_endpoint_owners(params, anchors)
        route_seed = self._preferred_route_seed(anchors, guide_worlds, seed)
        minimum = self._route_level_minimum(params["node_count"], anchors, route_seed)
        counts, iters = self._level_schedule(params["node_count"], minimum, params["iterations"])
        converged, max_disp, max_pen, max_active = False, 0.0, 0.0, 0
        for i, count in enumerate(counts):
            result = self._solve_open_level(
                fiber_prop, anchors, guide_worlds, oracle, params, seed, count,
                iters[i], route_seed)
            nodes, converged, max_disp, max_pen, active_count = result
            max_active = max(max_active, active_count)
            seed = nodes
        return ([] if seed is None else seed), converged, max_disp, max_pen, max_active

    def _route_level_minimum(self, node_count, anchors, route):
        route_count = min(max(0, int(node_count)), len(tuple(route or ())))
        return max(len(tuple(anchors or ())), route_count)

    def _solve_open_level(self, fiber, anchors, guides, oracle, params, seed, count, iters, route_seed):
        signature = params.get("_cache_signature")
        nodes, pinned, targets = self._build_level_nodes(
            fiber, anchors, guides, count, seed, signature)
        active = self._active_colliders(oracle, nodes, params["margin"])
        local = self._level_params(params, iters)
        local["surface_route_seed"] = bool(guides)
        local["pin_owners"] = self._pin_owners(anchors, targets)
        result = self._run_iterations(nodes, [p.copy() for p in nodes], pinned, targets,
                                      oracle, active, local)
        converged, disp, pen = self._restore_and_validate_open(
            nodes, route_seed, oracle, local, targets, *result)
        active = self._active_colliders(oracle, nodes, local["margin"])
        return nodes, converged, disp, pen, len(active)

    def _preferred_route_seed(self, anchors, guides, seed):
        if seed and len(seed) > len(anchors):
            return [point.copy() for point in seed]
        if guides:
            return self._route_seed_points(anchors, guides)
        return None if seed is None else [point.copy() for point in seed]

    def _restore_seed_if_needed(self, nodes, seed, oracle, params, pin_targets=None):
        self._restore_pins(nodes, pin_targets or {})
        residual = self._validated_open_residual(nodes, oracle, params)
        if seed is None or self._safe_open_residual(residual, params):
            return False, residual, 0.0
        candidate = self._preserve_polyline(seed, len(nodes))
        self._restore_pins(candidate, pin_targets or {})
        candidate_residual = self._validated_open_residual(candidate, oracle, params)
        if not self._safe_open_residual(candidate_residual, params):
            return False, residual, 0.0
        displacement = self._max_displacement(candidate, nodes)
        self._copy_nodes(nodes, candidate)
        return True, candidate_residual, displacement

    def _preserve_polyline(self, points, count):
        if not points or len(points) > count:
            return self._resample_polyline(points, count)
        nodes, _targets = self._build_chain_with_anchors(
            points[0], points[-1], points[1:-1], count)
        return nodes

    def _validated_open_residual(self, nodes, oracle, params):
        if not nodes or not all(self._finite_vector(point) for point in nodes):
            return float("inf")
        return float(self._final_residual(nodes, oracle, params))

    def _safe_open_residual(self, residual, params):
        return isfinite(float(residual)) and float(residual) < float(params.get("eps_pen", 1.0e-5))

    def _restore_and_validate_open(self, nodes, seed, oracle, params, targets, converged, max_disp, max_pen):
        restored, residual, fallback_disp = self._restore_seed_if_needed(
            nodes, seed, oracle, params, targets)
        safe = self._safe_open_residual(residual, params)
        displacement = max(float(max_disp), float(fallback_disp))
        return bool(converged and safe and not restored), displacement, residual

    def _validated_route_seed(self, route, count, oracle, params, targets):
        candidate = self._preserve_polyline(route, count)
        self._restore_pins(candidate, targets)
        residual = self._validated_open_residual(candidate, oracle, params)
        return candidate if self._safe_open_residual(residual, params) else None

    def _route_seed_preferred(self, params, pin_targets):
        return bool(params.get("surface_route_seed") or len(dict(pin_targets or {})) > 2)

    def _pin_owners(self, anchors, targets):
        indices = tuple(sorted(targets))
        return {index: str(anchor.owner_id or "") for index, anchor in zip(indices, anchors)}

    def _with_endpoint_owners(self, params, anchors):
        out = dict(params)
        out["endpoint_owners"] = (str(anchors[0].owner_id or ""), str(anchors[-1].owner_id or ""))
        return out

    def _level_counts(self, node_count, anchor_count):
        target = max(1, int(node_count))
        count = min(target, max(8, int(anchor_count)))
        out = [count]
        while out[-1] < target:
            out.append(min(target, out[-1] * 2))
        return out

    def _level_schedule(self, node_count, anchor_count, total):
        counts = self._level_counts(node_count, anchor_count)
        counts = counts[-min(len(counts), max(1, int(total))):]
        return counts, self._split_iterations(total, len(counts))

    def _split_iterations(self, total, level_count):
        total, level_count = max(1, int(total)), max(1, int(level_count))
        weights = [1 << i for i in range(level_count)]
        remaining = max(0, total - level_count)
        shares = [remaining * weight / float(sum(weights)) for weight in weights]
        out = [1 + int(share) for share in shares]
        order = sorted(range(level_count), key=lambda i: shares[i] - int(shares[i]), reverse=True)
        for index in order[:total - sum(out)]:
            out[index] += 1
        return out

    def _build_level_nodes(self, fiber_prop, anchors, guide_worlds, node_count, seed, signature=None):
        node_count = max(int(node_count), len(anchors))
        guides = self._bounded_guides(anchors, guide_worlds, node_count)
        route = self._route_seed_points(anchors, guides)
        nodes_init, targets = self._level_seed_layout(route, anchors, seed, node_count)
        seed_nodes = None if seed is None else nodes_init
        nodes = self._seed_or_cache_nodes(fiber_prop, nodes_init, node_count, seed_nodes, signature)
        pinned = [False] * node_count
        for idx, pt in targets.items():
            nodes[idx], pinned[idx] = pt.copy(), True
        return nodes, pinned, targets

    def _level_seed_layout(self, route, anchors, seed, count):
        if seed and len(seed) <= count:
            return self._preserved_seed_layout(seed, anchors, count)
        nodes, _targets = self._build_chain_with_anchors(
            route[0], route[-1], route[1:-1], count)
        targets = self._level_pin_targets(route, anchors, count)
        return (self._resample_polyline(seed, count) if seed else nodes), targets

    def _preserved_seed_layout(self, seed, anchors, count):
        nodes, source_targets = self._build_chain_with_anchors(
            seed[0], seed[-1], seed[1:-1], count)
        keys = tuple(sorted(source_targets))
        raw = [min(keys, key=lambda key: (source_targets[key] - anchor.point).length_squared)
               for anchor in anchors]
        indices = self._spread_pin_indices(raw, count)
        return nodes, {index: anchors[i].point.copy() for i, index in enumerate(indices)}

    def _bounded_guides(self, anchors, guides, count):
        limit = max(0, int(count) - len(tuple(anchors or ())))
        guides = tuple(guides or ())
        if len(guides) <= limit:
            return [point.copy() for point in guides]
        route = [anchors[0].point, *guides, anchors[-1].point]
        return self._resample_polyline(route, limit + 2)[1:-1]

    def _level_pin_targets(self, route, anchors, count):
        return self._anchor_pin_targets(route, anchors, count)

    def _route_pin_targets(self, route, count):
        edges = self._distribute_segment_edges(route, len(route) - 1, count - 1)
        _nodes, targets = self._compose_nodes_from_edges(route, edges)
        return targets

    def _route_seed_points(self, anchors, guide_worlds):
        if not guide_worlds:
            return [anchor.point.copy() for anchor in tuple(anchors or ())]
        points = [anchors[0].point.copy()]
        points.extend(point.copy() for point in tuple(guide_worlds or ()))
        points.append(anchors[-1].point.copy())
        return points

    def _anchor_pin_targets(self, route, anchors, count):
        indices = self._anchor_pin_indices(route, anchors, count)
        return {idx: anchors[i].point.copy() for i, idx in enumerate(indices)}

    def _anchor_pin_indices(self, route, anchors, count):
        spans, _total = self._polyline_spans(route)
        raw = [self._anchor_pin_index(route, spans, i, len(anchors), anchors[i].point, count) for i in range(len(anchors))]
        return self._spread_pin_indices(raw, count)

    def _anchor_pin_index(self, route, spans, order, anchor_count, point, count):
        if order <= 0:
            return 0
        if order >= anchor_count - 1:
            return count - 1
        total = max(spans[-1], 1.0e-9)
        return round(self._route_point_distance(route, spans, point) * (count - 1) / total)

    def _route_point_distance(self, route, spans, point):
        best = min(range(len(route)), key=lambda i: (route[i] - point).length_squared)
        return spans[best]

    def _spread_pin_indices(self, raw, count):
        out, prev, last = [], -1, max(0, count - 1)
        for i, value in enumerate(tuple(raw or ())):
            high = last - (len(raw) - 1 - i)
            out.append(max(prev + 1, min(high, int(value))))
            prev = out[-1]
        return out

    def _level_params(self, params, iterations):
        local = dict(params)
        local["iterations"] = max(1, int(iterations))
        local["min_iters"] = min(local["iterations"], max(1, local["iterations"] // 4))
        return local

    def _run_iterations(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params):
        converged, max_disp, max_pen = False, 0.0, 0.0
        colliders = self._active_colliders(oracle, nodes, params["margin"])
        safe = first_safe = self._safe_snapshot(nodes, oracle, colliders, params, skip_ends=True, pinned=pinned)
        guards = {}
        for it in range(params["iterations"]):
            local = self._collision_context_params(params)
            colliders = self._active_colliders(oracle, nodes, params["margin"])
            next_guards = {}
            max_disp, max_pen, alpha = self._open_step(nodes, prev_nodes, pinned, pin_targets, oracle, colliders, local, it, guards, next_guards)
            if self._blocked_clear(alpha, max_pen, local): break
            guards = next_guards if alpha >= 0.999999 else {}
            prev_nodes, colliders, safe = self._post_iteration_state(nodes, oracle, local, safe, skip_ends=True, pinned=pinned)
            if self._iteration_converged(it, max_disp, max_pen, params): converged = True; break
        return self._finish_open_iterations(nodes, safe, first_safe, oracle, colliders, params, converged, max_disp, max_pen)

    def _finish_open_iterations(self, nodes, safe, first_safe, oracle, colliders, params, converged, max_disp, max_pen):
        safe = self._restore_choice(safe, first_safe, oracle, colliders, params, skip_ends=True)
        self._restore_safe_snapshot(nodes, safe, oracle, colliders, params, skip_ends=True)
        residual = self._final_residual(nodes, oracle, params)
        return bool(converged and residual < params["eps_pen"]), max_disp, residual

    def _restore_unconverged(self, nodes, safe, first_safe, oracle, colliders, params, max_disp, max_pen, cyclic=False, skip_ends=False):
        safe = self._restore_choice(safe, first_safe, oracle, colliders, params, cyclic, skip_ends)
        self._restore_safe_snapshot(nodes, safe, oracle, colliders, params, cyclic, skip_ends)
        return False, max_disp, self._final_residual(nodes, oracle, params, cyclic)

    def _iteration_converged(self, it, max_disp, max_pen, params):
        return it + 1 >= params["min_iters"] and max_disp < params["eps_disp"] and max_pen < params["eps_pen"]

    def _blocked_clear(self, alpha, max_pen, params):
        _ = max_pen
        return bool(self._uses_v2(params) and params.get("_stop_when_blocked") and alpha <= 0.0)

    def _collision_context_params(self, params):
        local = dict(params)
        context = params.get("_collision_context")
        if context is None:
            context = {"colliders": {}, "hits": {}, "pen": {}, "zones": {}, "clear": {}}
            params["_collision_context"] = context
        local["_collision_context"] = context
        return local

    def _open_step(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards):
        telemetry_count("fiber_iterations")
        _ = prev_nodes
        start = [p.copy() for p in nodes]
        candidate = [p.copy() for p in start]
        trial_disp, trial_pen = self._solver_iteration(candidate, start, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards)
        params["_v2_contact"] = self._uses_v2(params) and trial_pen > params["eps_pen"]
        alpha, pen = self._accept_candidate(nodes, start, candidate, oracle, params, skip_ends=True)
        return self._max_displacement(nodes, start), self._accepted_pen(alpha, pen, trial_pen), alpha

    def _restore_choice(self, safe, fallback, oracle, colliders, params, cyclic=False, skip_ends=False):
        safe = self._valid_snapshot(safe, oracle, colliders, params, cyclic, skip_ends)
        return safe or self._valid_snapshot(fallback, oracle, colliders, params, cyclic, skip_ends)

    def _valid_snapshot(self, snapshot, oracle, colliders, params, cyclic, skip_ends):
        if snapshot is None:
            return None
        colliders = self._snapshot_colliders(oracle, snapshot, colliders, params["margin"])
        return snapshot if self._segments_clear(snapshot, oracle, colliders, params, cyclic, skip_ends) else None

    def _snapshot_colliders(self, oracle, nodes, colliders, margin):
        if hasattr(oracle, "active_colliders_for_polyline"):
            return self._active_colliders(oracle, nodes, margin)
        return colliders

    def _post_iteration_state(self, nodes, oracle, params, safe, cyclic=False, skip_ends=False, pinned=None):
        self._clear_owner_zone_cache(params)
        colliders = self._active_colliders(oracle, nodes, params["margin"])
        safe = self._refresh_safe_snapshot(safe, nodes, oracle, colliders, params, cyclic, skip_ends, pinned)
        return [p.copy() for p in nodes], colliders, safe

    def _safe_snapshot(self, nodes, oracle, colliders, params, cyclic=False, skip_ends=False, pinned=None):
        return [p.copy() for p in nodes] if self._snapshot_clear(nodes, oracle, colliders, params, cyclic, skip_ends, pinned) else None

    def _refresh_safe_snapshot(self, safe, nodes, oracle, colliders, params, cyclic=False, skip_ends=False, pinned=None):
        if not self._snapshot_clear(nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
            return safe
        candidate = [p.copy() for p in nodes]
        return candidate if self._snapshot_better(candidate, safe, cyclic) else safe

    def _restore_safe_snapshot(self, nodes, safe, oracle, colliders, params, cyclic=False, skip_ends=False):
        if safe is None:
            return
        colliders = self._snapshot_colliders(oracle, nodes, colliders, params["margin"])
        if self._segments_clear(nodes, oracle, colliders, params, cyclic, skip_ends) and not self._snapshot_better(safe, nodes, cyclic):
            return
        self._copy_nodes(nodes, safe)

    def _final_residual(self, nodes, oracle, params, cyclic=False):
        self._clear_owner_zone_cache(params)
        colliders = self._active_colliders(oracle, nodes, params["margin"])
        local = dict(params, segment_collisions=True)
        zones = self._owner_zone_limits(nodes, oracle, colliders, local)
        node_pen = max((self._sample_penetration(point, oracle,
                        self._node_colliders(nodes, i, oracle, colliders, local, zones))
                        for i, point in enumerate(nodes)), default=0.0)
        edge_pen = self._state_penetration(nodes, oracle, colliders, local, cyclic, False)
        return max(float(node_pen), float(edge_pen))

    def _snapshot_better(self, candidate, current, cyclic):
        if current is None:
            return True
        return self._path_length(candidate, cyclic) < self._path_length(current, cyclic) - 1.0e-9

    def _snapshot_clear(self, nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
        if not self._snapshot_segments_clear(nodes, oracle, colliders, params, cyclic, skip_ends):
            return False
        return self._free_nodes_clear(nodes, oracle, colliders, params, cyclic, skip_ends, pinned)

    def _snapshot_segments_clear(self, nodes, oracle, colliders, params, cyclic, skip_ends):
        safe_params = dict(params)
        safe_params["segment_collisions"] = True
        return self._segments_clear(nodes, oracle, colliders, safe_params, cyclic, skip_ends)

    def _free_nodes_clear(self, nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
        indices = self._free_node_indices(len(nodes), pinned, cyclic, skip_ends)
        zones = self._owner_zone_limits(nodes, oracle, colliders, params)
        return all(self._sample_penetration(nodes[i], oracle, self._node_colliders(nodes, i, oracle, colliders, params, zones)) <= 0.0 for i in indices)

    def _free_node_indices(self, count, pinned, cyclic, skip_ends):
        for i in range(count):
            if skip_ends and not cyclic and i in (0, count - 1):
                continue
            if pinned is not None and self._is_pinned(pinned, i):
                continue
            yield i

    def _accept_candidate(self, nodes, start, candidate, oracle, params, cyclic=False, skip_ends=False):
        if self._uses_v2(params) and params.get("_trusted_clear_start") and native_ccd_enabled():
            return self._v2_native_backtrack(nodes, start, candidate, oracle, params, cyclic)
        if params.get("_v2_contact"):
            return self._backtrack_candidate(nodes, start, candidate, oracle, params, cyclic, skip_ends)
        colliders = self._candidate_colliders(oracle, start, candidate, params)
        if self._candidate_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends):
            self._copy_nodes(nodes, candidate)
            return 1.0, 0.0
        return self._backtrack_candidate(nodes, start, candidate, oracle, params, cyclic, skip_ends)

    def _candidate_clear(self, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if params.get("_v2_contact"):
            return self._v2_candidate_clear(candidate, oracle, colliders, params, cyclic, skip_ends)
        if not self._segments_clear(candidate, oracle, colliders, params, cyclic, skip_ends):
            return False
        if not self._moved_points_clear(candidate, start, candidate, oracle, colliders, params, cyclic, skip_ends):
            return False
        if not self._candidate_start_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends):
            return True
        return self._sweep_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends)

    def _v2_candidate_clear(self, candidate, oracle, colliders, params, cyclic, skip_ends):
        return self._segments_clear(candidate, oracle, colliders, params, cyclic, skip_ends)

    def _candidate_start_clear(self, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not self._segments_clear(start, oracle, colliders, params, cyclic, skip_ends):
            return False
        return self._moved_points_clear(start, start, candidate, oracle, colliders, params, cyclic, skip_ends)

    def _backtrack_candidate(self, nodes, start, candidate, oracle, params, cyclic, skip_ends):
        colliders = self._candidate_colliders(oracle, start, candidate, params)
        if params.get("_v2_contact"):
            return self._v2_backtrack(nodes, start, candidate, oracle, colliders, params, cyclic, skip_ends)
        trials, high = [], 1.0
        for alpha in self._backtrack_alphas():
            trial = self._interpolate_nodes(start, candidate, alpha)
            if self._candidate_clear(start, trial, oracle, colliders, params, cyclic, skip_ends):
                return self._accept_refined_alpha(nodes, start, candidate, alpha, high, oracle, colliders, params, cyclic, skip_ends)
            trials.append((trial, alpha))
            high = alpha
        return self._best_backtrack(nodes, start, trials, oracle, colliders, params, cyclic, skip_ends)

    def _v2_backtrack(self, nodes, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not params.get("_trusted_clear_start"):
            return self._best_backtrack(nodes, start, self._v2_trials(start, candidate),
                                        oracle, colliders, params, cyclic, skip_ends)
        if native_ccd_enabled():
            return self._v2_native_backtrack(nodes, start, candidate, oracle, params, cyclic)
        for alpha in self._backtrack_alphas():
            trial = self._interpolate_nodes(start, candidate, alpha)
            if self._v2_candidate_clear(trial, oracle, colliders, params, cyclic, skip_ends):
                self._copy_nodes(nodes, trial)
                return alpha, 0.0
        return 0.0, 0.0

    def _v2_native_backtrack(self, nodes, start, candidate, oracle, params, cyclic):
        result = native_collision_free_step(self, start, candidate, oracle, params, cyclic)
        if not result.initially_valid or result.safe_step <= 0.0:
            return 0.0, 0.0
        alpha = min(1.0, float(result.safe_step))
        trial = self._interpolate_nodes(start, candidate, alpha)
        self._copy_nodes(nodes, trial)
        return alpha, 0.0

    def _v2_trials(self, start, candidate):
        return [(self._interpolate_nodes(start, candidate, alpha), alpha)
                for alpha in (1.0, *self._backtrack_alphas())]

    def _best_backtrack(self, nodes, start, trials, oracle, colliders, params, cyclic, skip_ends):
        start_pen = self._state_penetration(start, oracle, colliders, params, cyclic, skip_ends)
        best = (start_pen, 0.0, start)
        for trial, alpha in trials:
            best = self._best_penalty_choice(best, trial, alpha, oracle, colliders, params, cyclic, skip_ends)
        return self._use_best_candidate(nodes, best, start_pen)

    def _accept_refined_alpha(self, nodes, start, candidate, alpha, high, oracle, colliders, params, cyclic, skip_ends):
        if not self._uses_v2(params):
            alpha = self._refined_clear_alpha(start, candidate, alpha, high, oracle, colliders, params, cyclic, skip_ends)
        trial = self._interpolate_nodes(start, candidate, alpha)
        self._copy_nodes(nodes, trial)
        return alpha, 0.0

    def _refined_clear_alpha(self, start, candidate, low, high, oracle, colliders, params, cyclic, skip_ends):
        mid = (low + high) * 0.5
        trial = self._interpolate_nodes(start, candidate, mid)
        if self._candidate_clear(start, trial, oracle, colliders, params, cyclic, skip_ends):
            return mid
        return low

    def _best_penalty_choice(self, best, trial, alpha, oracle, colliders, params, cyclic, skip_ends):
        if best[0] <= 0.0:
            return best
        pen = self._state_penetration(trial, oracle, colliders, params, cyclic, skip_ends)
        return (pen, alpha, trial) if pen < best[0] else best

    def _use_best_candidate(self, nodes, best, start_pen):
        pen, alpha, trial = best
        if alpha > 0.0 and pen < start_pen:
            self._copy_nodes(nodes, trial)
            return alpha, pen
        return 0.0, start_pen

    def _accepted_pen(self, alpha, accepted_pen, trial_pen):
        return max(float(accepted_pen), float(trial_pen)) if alpha >= 0.999999 else float(accepted_pen)

    def _candidate_colliders(self, oracle, start, candidate, params):
        return self._active_colliders(oracle, tuple(start) + tuple(candidate), params["margin"])

    def _sweep_clear(self, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        for alpha in self._sweep_alphas():
            trial = self._interpolate_nodes(start, candidate, alpha)
            if not self._segments_clear(trial, oracle, colliders, params, cyclic, skip_ends):
                return False
        return self._node_paths_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends)

    def _node_paths_clear(self, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not params["segment_collisions"]:
            return True
        zones = self._owner_zone_limits(candidate, oracle, colliders, params)
        return all(self._node_path_clear(start, candidate, i, oracle, colliders, params, zones) for i in self._moving_node_indices(start, candidate, cyclic, skip_ends))

    def _node_path_clear(self, start, candidate, index, oracle, colliders, params, zones):
        cols = self._node_colliders(candidate, index, oracle, colliders, params, zones)
        return self._segment_penetration_cached(start[index], candidate[index], oracle, cols, params) <= 0.0

    def _moved_points_clear(self, points, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not params["segment_collisions"]:
            return True
        values = self._moving_node_indices(start, candidate, cyclic, skip_ends)
        zones = self._owner_zone_limits(points, oracle, colliders, params)
        return all(self._sample_penetration(points[i], oracle, self._node_colliders(points, i, oracle, colliders, params, zones)) <= 0.0 for i in values)

    def _moving_node_indices(self, start, candidate, cyclic, skip_ends):
        last = len(start) - 1
        for i in range(len(start)):
            if skip_ends and not cyclic and i in (0, last):
                continue
            if (candidate[i] - start[i]).length_squared > 1.0e-18:
                yield i

    def _segments_clear(self, nodes, oracle, colliders, params, cyclic=False, skip_ends=False):
        if not params["segment_collisions"]:
            return True
        key = self._state_penetration_key(nodes, colliders, params, cyclic, skip_ends)
        ctx = self._collision_context(params)
        if ctx is None:
            return self._segments_clear_uncached(nodes, oracle, colliders, params, cyclic, skip_ends)
        cache = ctx.setdefault("clear", {})
        if key not in cache:
            cache[key] = self._segments_clear_uncached(nodes, oracle, colliders, params, cyclic, skip_ends)
        return cache[key]

    def _segments_clear_uncached(self, nodes, oracle, colliders, params, cyclic, skip_ends):
        pairs = self._clear_segment_pairs(len(nodes), cyclic, skip_ends)
        zones = self._owner_zone_limits(nodes, oracle, colliders, params)
        return all(not self._pair_blocked(nodes, a, b, oracle, colliders, params, zones) for a, b in pairs)

    def _state_penetration(self, nodes, oracle, colliders, params, cyclic=False, skip_ends=False):
        if not params["segment_collisions"]:
            return 0.0
        key = self._state_penetration_key(nodes, colliders, params, cyclic, skip_ends)
        ctx = self._collision_context(params)
        if ctx is None:
            return self._state_penetration_uncached(nodes, oracle, colliders, params, cyclic, skip_ends)
        cache = ctx.setdefault("pen", {})
        if key not in cache:
            cache[key] = self._state_penetration_uncached(nodes, oracle, colliders, params, cyclic, skip_ends)
        return cache[key]

    def _state_penetration_uncached(self, nodes, oracle, colliders, params, cyclic, skip_ends):
        pairs = self._clear_segment_pairs(len(nodes), cyclic, skip_ends)
        zones = self._owner_zone_limits(nodes, oracle, colliders, params)
        return max((self._pair_penetration(nodes, a, b, oracle, colliders, params, zones) for a, b in pairs), default=0.0)

    def _state_penetration_key(self, nodes, colliders, params, cyclic, skip_ends):
        owners = self._pin_owner_items(nodes, params)
        return self._nodes_key(nodes), self._colliders_key(colliders), owners, bool(cyclic), bool(skip_ends)

    def _pair_blocked(self, nodes, a_idx, b_idx, oracle, colliders, params, zones):
        cols = self._pair_colliders(nodes, a_idx, b_idx, oracle, colliders, params, zones)
        return any(self._owner_pair_blocked(nodes, a_idx, b_idx, oracle, c, params, zones)
                   for c in cols)

    def _pair_penetration(self, nodes, a_idx, b_idx, oracle, colliders, params, zones=None):
        zones = zones or self._owner_zone_limits(nodes, oracle, colliders, params)
        cols = self._pair_colliders(nodes, a_idx, b_idx, oracle, colliders, params, zones)
        values = (self._owner_pair_penetration(nodes, a_idx, b_idx, oracle, c, params, zones)
                  for c in cols)
        return max(values, default=0.0)

    def _owner_pair_blocked(self, nodes, first, second, oracle, collider, params, zones):
        segment = self._owner_trimmed_pair(nodes, first, second, oracle, collider, params, zones)
        if segment is None:
            return False
        return self._segment_blocked_cached(segment[0], segment[1], oracle, (collider,), params)

    def _owner_pair_penetration(self, nodes, first, second, oracle, collider, params, zones):
        segment = self._owner_trimmed_pair(nodes, first, second, oracle, collider, params, zones)
        if segment is None:
            return 0.0
        return self._segment_penetration_cached(segment[0], segment[1], oracle, (collider,), params)

    def _owner_trimmed_pair(self, nodes, first, second, oracle, collider, params, zones):
        interval = self._owner_trim_interval(nodes, first, second, oracle, collider, params, zones)
        if interval is None:
            return None
        start, end = nodes[first], nodes[second]
        return start.lerp(end, interval[0]), start.lerp(end, interval[1]), interval

    def _owner_trim_interval(self, nodes, first, second, oracle, collider, params, zones):
        length = (nodes[second] - nodes[first]).length
        if length <= 1.0e-9:
            return None
        radius = min(1.0, self._owner_contact_radius(oracle, params) / length)
        low = radius if not self._node_collider_allowed(collider, first, zones) else 0.0
        high = 1.0 - (radius if not self._node_collider_allowed(collider, second, zones) else 0.0)
        return None if high <= low else (low, high)

    def _owner_contact_radius(self, oracle, params):
        clearance = max(0.0, float(getattr(oracle, "clearance", 0.0)))
        return max(1.0e-5, clearance * self._owner_contact_factor(params))

    def _owner_contact_factor(self, params):
        return 1.0 if bool(params.get("surface_route_seed")) else 8.0

    def _pair_colliders(self, nodes, a_idx, b_idx, oracle, colliders, params, zones=None):
        zones = zones or self._owner_zone_limits(nodes, oracle, colliders, params)
        bounds = self._query_bounds((nodes[a_idx], nodes[b_idx]), params)
        key = self._collider_cache_key("pair", bounds, a_idx, b_idx, self._zones_key(zones))
        return self._cached_colliders(params, key, self._filter_pair_colliders,
                                      colliders, a_idx, b_idx, zones, bounds)

    def _node_colliders(self, nodes, index, oracle, colliders, params, zones=None):
        zones = zones or self._owner_zone_limits(nodes, oracle, colliders, params)
        bounds = self._query_bounds((nodes[index],), params)
        key = self._collider_cache_key("node", bounds, index, self._zones_key(zones))
        return self._cached_colliders(params, key, self._filter_node_colliders,
                                      colliders, index, zones, bounds)

    def _cached_colliders(self, params, key, factory, *args):
        ctx = self._collision_context(params)
        if ctx is None:
            return factory(*args)
        cache = ctx.setdefault("colliders", {})
        if key not in cache:
            cache[key] = factory(*args)
        return cache[key]

    def _filter_pair_colliders(self, colliders, a_idx, b_idx, zones, bounds):
        return tuple(c for c in colliders if self._pair_collider_allowed(c, a_idx, b_idx, zones)
                     and self._collider_overlaps(c, bounds))

    def _filter_node_colliders(self, colliders, index, zones, bounds):
        return tuple(c for c in colliders if self._node_collider_allowed(c, index, zones)
                     and self._collider_overlaps(c, bounds))

    def _pair_collider_allowed(self, collider, a_idx, b_idx, zones):
        _ = collider, a_idx, b_idx, zones
        return True

    def _node_collider_allowed(self, collider, index, zones):
        sid = str(collider["sid"])
        return not any(start <= index <= end for start, end in (zones or {}).get(sid, ()))

    def _owner_zone_limits(self, nodes, oracle, colliders, params):
        owners = self._pin_owner_items(nodes, params)
        key = self._owner_zone_key(nodes, colliders, owners)
        ctx = self._collision_context(params)
        if ctx is None:
            return self._compute_owner_zone_limits(nodes, oracle, colliders, owners)
        cache = ctx.setdefault("zones", {})
        if key not in cache:
            cache[key] = self._compute_owner_zone_limits(nodes, oracle, colliders, owners)
        return cache[key]

    def _compute_owner_zone_limits(self, nodes, oracle, colliders, owners):
        _ = oracle
        zones = {}
        known = {str(c["sid"]) for c in tuple(colliders or ())}
        for index, owner in owners:
            if owner and owner in known:
                pin = max(0, min(len(nodes) - 1, int(index)))
                zones.setdefault(owner, []).append((pin, pin))
        return {sid: tuple(values) for sid, values in zones.items()}

    def _pin_owner_items(self, nodes, params):
        values = dict(params.get("pin_owners", {}) or {})
        if values:
            return tuple(sorted((int(index), str(owner or "")) for index, owner in values.items()))
        start, end = tuple(params.get("endpoint_owners", ("", "")) or ("", ""))
        return ((0, str(start or "")), (max(0, len(nodes) - 1), str(end or "")))

    def _owner_zone_key(self, nodes, colliders, owners):
        return id(nodes), tuple(owners), self._colliders_key(colliders)

    def _clear_owner_zone_cache(self, params):
        context = self._collision_context(params)
        if context is not None:
            context.setdefault("zones", {}).clear()


    def _zones_key(self, zones):
        return tuple((sid, tuple(values)) for sid, values in sorted(zones.items()))

    def _owner_start_limit(self, nodes, oracle, collider):
        index = 0
        while collider is not None and index < len(nodes) and self._point_hits_collider(nodes[index], oracle, collider):
            index += 1
        return index

    def _owner_end_limit(self, nodes, oracle, collider):
        index = len(nodes) - 1
        while collider is not None and index >= 0 and self._point_hits_collider(nodes[index], oracle, collider):
            index -= 1
        return index + 1

    def _collider_by_sid(self, colliders, sid):
        return next((c for c in colliders if str(c["sid"]) == str(sid or "")), None)

    def _point_hits_collider(self, point, oracle, collider):
        return self._sample_penetration(point, oracle, (collider,)) > 0.0

    def _query_bounds(self, points, params):
        pad = max(0.0, float(params.get("margin", 0.0)) * 2.0)
        xs, ys, zs = [p.x for p in points], [p.y for p in points], [p.z for p in points]
        return Vector((min(xs) - pad, min(ys) - pad, min(zs) - pad)), Vector((max(xs) + pad, max(ys) + pad, max(zs) + pad))

    def _collider_overlaps(self, collider, bounds):
        if "mn" not in collider or "mx" not in collider:
            return True
        return self._bounds_overlap(bounds[0], bounds[1], collider["mn"], collider["mx"])

    def _bounds_overlap(self, a_mn, a_mx, b_mn, b_mx):
        return not (a_mx.x < b_mn.x or b_mx.x < a_mn.x or a_mx.y < b_mn.y or b_mx.y < a_mn.y or a_mx.z < b_mn.z or b_mx.z < a_mn.z)

    def _collision_context(self, params):
        return params.get("_collision_context") if isinstance(params, dict) else None

    def _collider_cache_key(self, kind, bounds, *parts):
        return kind, self._bounds_key(bounds), tuple(parts)

    def _bounds_key(self, bounds):
        return tuple(round(v, 5) for p in bounds for v in (p.x, p.y, p.z))

    def _nodes_key(self, nodes):
        return tuple(self._point_key(point) for point in nodes)

    def _colliders_key(self, colliders):
        return tuple(id(collider) for collider in tuple(colliders or ()))

    def _copy_nodes(self, nodes, source):
        for i, point in enumerate(source):
            nodes[i] = point.copy()

    def _path_length(self, nodes, cyclic=False):
        pairs = self._segment_pairs(len(nodes), cyclic)
        return sum((nodes[b] - nodes[a]).length for a, b in pairs)

    def _interpolate_nodes(self, start, candidate, alpha):
        return [a.lerp(b, alpha) for a, b in zip(start, candidate)]

    def _backtrack_alphas(self):
        return (0.5, 0.25, 0.125, 0.0625, 0.03125)

    def _sweep_alphas(self):
        return (0.25, 0.5, 0.75)

    def _clear_segment_pairs(self, count, cyclic, skip_ends):
        pairs = self._segment_pairs(count, cyclic)
        return pairs[1:-1] if skip_ends and not cyclic else pairs

    def _store_status(self, fiber_prop, converged, max_disp, max_pen):
        self._clear_invalid_state(fiber_prop)
        set_fiber_not_converged(fiber_prop, not converged)
        set_fiber_eps_disp(fiber_prop, float(max_disp))
        set_fiber_eps_pen(fiber_prop, float(max_pen))

    def _guide_worlds(self, root, scene, runtime_registry, fiber_prop):
        anchors = self._route_anchors(root, scene, runtime_registry, fiber_prop)
        return [] if anchors is None else [anchor.point.copy() for anchor in anchors[1:-1]]

    def _build_chain_with_anchors(self, a_world, b_world, guides, node_count):
        anchors = [a_world] + [g.copy() for g in guides] + [b_world]
        seg_count = len(anchors) - 1
        total_edges = node_count - 1

        if seg_count <= 0:
            nodes = [a_world.lerp(b_world, i / float(max(1, total_edges))) for i in range(node_count)]
            return nodes, {0: a_world.copy(), node_count - 1: b_world.copy()}

        edges = self._distribute_segment_edges(anchors, seg_count, total_edges)
        nodes, pin_targets = self._compose_nodes_from_edges(anchors, edges)
        if len(nodes) == node_count:
            return nodes, pin_targets
        return self._fallback_nodes_with_pins(anchors, node_count)

    def _distribute_segment_edges(self, anchors, seg_count, total_edges):
        seg_lengths = [(anchors[i + 1] - anchors[i]).length for i in range(seg_count)]
        total_len = sum(seg_lengths)
        if total_len <= 1e-9:
            seg_lengths = [1.0] * seg_count
            total_len = float(seg_count)
        edges = [1] * seg_count
        remaining = total_edges - seg_count
        if remaining <= 0:
            return edges
        raw = [remaining * (d / total_len) for d in seg_lengths]
        self._add_integer_edges(edges, raw)
        self._add_fractional_edges(edges, raw, remaining - sum(int(v) for v in raw))
        return edges

    def _add_integer_edges(self, edges, raw):
        for i in range(len(edges)):
            edges[i] += int(raw[i])

    def _add_fractional_edges(self, edges, raw, leftover):
        if leftover <= 0:
            return
        frac = sorted([(raw[i] - int(raw[i]), i) for i in range(len(edges))], reverse=True)
        for k in range(leftover):
            edges[frac[k % len(frac)][1]] += 1

    def _compose_nodes_from_edges(self, anchors, edges):
        nodes, pin_targets, cursor = [], {}, 0
        for si, e in enumerate(edges):
            p0, p1 = anchors[si], anchors[si + 1]
            e = max(1, e)
            seg_nodes = [p0.lerp(p1, j / float(e)) for j in range(e + 1)]
            if si == 0:
                nodes.extend(seg_nodes)
                pin_targets[0] = anchors[0].copy()
                cursor = e
            else:
                nodes.extend(seg_nodes[1:])
                cursor += e
            pin_targets[cursor] = anchors[si + 1].copy()
        return nodes, pin_targets

    def _fallback_nodes_with_pins(self, anchors, node_count):
        nodes = [anchors[0].lerp(anchors[-1], i / float(max(1, node_count - 1))) for i in range(node_count)]
        pin_targets = {0: anchors[0].copy(), node_count - 1: anchors[-1].copy()}
        if len(anchors) > 2:
            for k in range(1, len(anchors) - 1):
                idx = int(round(k * (node_count - 1) / float(len(anchors) - 1)))
                idx = max(1, min(node_count - 2, idx))
                pin_targets[idx] = anchors[k].copy()
        return nodes, pin_targets

    def _endpoint_world(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        return resolve_fiber_endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)

    def _active_colliders(self, oracle, nodes, margin):
        _ = margin
        if not hasattr(oracle, "active_colliders_for_polyline"):
            return ()
        pad = oracle.active_padding() if hasattr(oracle, "active_padding") else max(0.05, oracle.clearance * 2.0, oracle.margin * 4.0)
        return oracle.active_colliders_for_polyline(nodes, padding=pad)

    def _apply_length_shortening(self, nodes, pinned, strength):
        n = len(nodes)
        if n < 3 or strength <= 0.0:
            return
        new_nodes = [p.copy() for p in nodes]
        s = max(0.0, min(1.0, strength))
        for i in range(1, n - 1):
            if not pinned[i]:
                new_nodes[i] = nodes[i].lerp((nodes[i - 1] + nodes[i + 1]) * 0.5, s)
        self._commit_free_nodes(nodes, new_nodes, pinned)

    def _apply_bend_smoothing(self, nodes, pinned, bend_stiff):
        n = len(nodes)
        if n < 3 or bend_stiff <= 0.0:
            return
        new_nodes = [p.copy() for p in nodes]
        s = max(0.0, min(1.0, bend_stiff))
        for i in range(1, n - 1):
            if not pinned[i]:
                new_nodes[i] = nodes[i] + ((nodes[i - 1] + nodes[i + 1]) * 0.5 - nodes[i]) * s
        self._commit_free_nodes(nodes, new_nodes, pinned)

    def _commit_free_nodes(self, nodes, new_nodes, pinned):
        for i in range(1, len(nodes) - 1):
            if not pinned[i]:
                nodes[i] = new_nodes[i]

    def _apply_collision_constraints(self, nodes, pinned, oracle, colliders, params):
        max_pen = 0.0
        zones = self._owner_zone_limits(nodes, oracle, colliders, params)
        for i in range(1, len(nodes) - 1):
            if pinned[i]:
                continue
            active = self._node_colliders(nodes, i, oracle, colliders, params, zones)
            x, pen = oracle.push_out_point(nodes[i], active)
            max_pen = max(max_pen, pen)
            nodes[i] = x
        return max_pen

    def _apply_segment_penalties(self, max_pen, nodes, pinned, oracle, colliders, params, cyclic=False):
        if not params["segment_collisions"]:
            return max_pen
        pen = self._apply_segment_collision_constraints(nodes, pinned, oracle, colliders, params, cyclic=cyclic)
        return max(max_pen, pen)

    def _rollback_segment_introductions(self, nodes, prev_nodes, pinned, oracle, colliders, params, cyclic=False, next_guards=None):
        if not params["segment_collisions"]:
            return
        for a_idx, b_idx in self._segment_pairs(len(nodes), cyclic):
            self._rollback_segment_pair(nodes, prev_nodes, pinned, oracle, colliders, params, a_idx, b_idx, next_guards)

    def _rollback_segment_pair(self, nodes, prev_nodes, pinned, oracle, colliders, params, a_idx, b_idx, next_guards=None):
        before = self._strict_pair_penetration(prev_nodes, a_idx, b_idx, oracle, colliders, params)
        after = self._strict_pair_penetration(nodes, a_idx, b_idx, oracle, colliders, params)
        if before <= 0.0 and after > 0.0:
            index = self._rollback_index(pinned, a_idx, b_idx)
            restored = None if index is None else self._restore_iteration_node(nodes, prev_nodes, pinned, index)
            self._record_guard_target(next_guards, index, restored)

    def _strict_pair_penetration(self, nodes, first, second, oracle, colliders, params):
        bounds = self._query_bounds((nodes[first], nodes[second]), params)
        active = tuple(c for c in colliders if self._collider_overlaps(c, bounds))
        return self._segment_penetration_cached(nodes[first], nodes[second], oracle, active, params)

    def _rollback_index(self, pinned, a_idx, b_idx):
        if not self._is_pinned(pinned, b_idx):
            return b_idx
        return None if self._is_pinned(pinned, a_idx) else a_idx

    def _record_guard_target(self, next_guards, index, point):
        if next_guards is not None and index is not None and point is not None:
            next_guards[int(index)] = point.copy()

    def _segment_introduced_collision(self, nodes, prev_nodes, oracle, colliders, params, a_idx, b_idx):
        before = self._strict_pair_penetration(prev_nodes, a_idx, b_idx, oracle, colliders, params)
        after = self._strict_pair_penetration(nodes, a_idx, b_idx, oracle, colliders, params)
        return before <= 0.0 and after > 0.0

    def _apply_segment_collision_constraints(self, nodes, pinned, oracle, colliders, params, cyclic=False):
        pairs = self._segment_pairs(len(nodes), cyclic)
        max_pen = 0.0
        zones = self._owner_zone_limits(nodes, oracle, colliders, params)
        for a_idx, b_idx in pairs:
            cols = self._pair_colliders(nodes, a_idx, b_idx, oracle, colliders, params, zones)
            pen = self._owner_pair_penalty(nodes, pinned, oracle, cols, a_idx, b_idx, params, zones)
            max_pen = max(max_pen, pen)
        return max_pen

    def _owner_pair_penalty(self, nodes, pinned, oracle, colliders, first, second, params, zones):
        maximum = 0.0
        for collider in tuple(colliders or ()):
            segment = self._owner_trimmed_pair(nodes, first, second, oracle, collider, params, zones)
            if self._trimmed_pair_needs_penalty(segment, oracle, collider, params):
                maximum = max(maximum, self._trimmed_segment_penalty(
                    nodes, pinned, oracle, collider, first, second, params, segment))
        return maximum

    def _trimmed_pair_needs_penalty(self, segment, oracle, collider, params):
        if segment is None:
            return False
        if not hasattr(oracle, "segment_hit_samples"):
            return True
        return self._cached_segment_ray(segment[0], segment[1], oracle, (collider,), params)

    def _trimmed_segment_penalty(self, nodes, pinned, oracle, collider, first, second, params, segment):
        start, end, interval = segment
        move_a, move_b, maximum = self._zero_vec(), self._zero_vec(), 0.0
        for value in self._segment_samples_for_cached(start, end, oracle, (collider,), params):
            t = interval[0] + (interval[1] - interval[0]) * value
            da, db, pen = self._segment_sample_correction(
                nodes[first], nodes[second], pinned, oracle, (collider,), first, second, t)
            move_a, move_b, maximum = move_a + da, move_b + db, max(maximum, pen)
        self._apply_segment_moves(nodes, pinned, first, second, move_a, move_b)
        return maximum

    def _pair_needs_segment_penalty(self, nodes, a_idx, b_idx, oracle, colliders, params):
        if self._no_real_colliders(oracle, colliders):
            return False
        if not hasattr(oracle, "segment_hit_samples"):
            return True
        return self._cached_segment_ray(nodes[a_idx], nodes[b_idx], oracle, colliders, params)

    def _segment_pairs(self, count, cyclic):
        pairs = [(i, i + 1) for i in range(max(0, count - 1))]
        return pairs + ([(count - 1, 0)] if cyclic and count > 2 else [])

    def _segment_penalty(self, nodes, pinned, oracle, colliders, a_idx, b_idx, params):
        move_a, move_b, max_pen = self._zero_vec(), self._zero_vec(), 0.0
        for t in self._segment_samples_for_cached(nodes[a_idx], nodes[b_idx], oracle, colliders, params):
            da, db, pen = self._segment_sample_correction(nodes[a_idx], nodes[b_idx], pinned, oracle, colliders, a_idx, b_idx, t)
            move_a, move_b = move_a + da, move_b + db
            max_pen = max(max_pen, pen)
        self._apply_segment_moves(nodes, pinned, a_idx, b_idx, move_a, move_b)
        return max_pen

    def _segment_samples(self):
        return (0.25, 0.5, 0.75)

    def _segment_samples_for(self, a, b, oracle, colliders):
        if not hasattr(oracle, "segment_hit_samples"):
            return self._segment_samples()
        return self._merged_segment_samples(self._segment_samples(), oracle.segment_hit_samples(a, b, colliders))

    def _segment_samples_for_cached(self, a, b, oracle, colliders, params):
        if not hasattr(oracle, "segment_hit_samples"):
            return self._segment_samples()
        return self._merged_segment_samples(self._segment_samples(), self._cached_segment_hits(a, b, oracle, colliders, params))

    def _merged_segment_samples(self, base, hits):
        values = {round(float(t), 6) for t in base}
        values.update(round(float(t), 6) for t in tuple(hits or ()) if 0.0 < float(t) < 1.0)
        return tuple(sorted(values))

    def _segment_penetration(self, a, b, oracle, colliders):
        if self._no_real_colliders(oracle, colliders):
            return 0.0
        return max(self._sample_penetration(a.lerp(b, t), oracle, colliders) for t in self._segment_samples_for(a, b, oracle, colliders))

    def _segment_penetration_cached(self, a, b, oracle, colliders, params):
        if self._no_real_colliders(oracle, colliders):
            return 0.0
        samples = self._segment_samples_for_cached(a, b, oracle, colliders, params)
        sample_pen = max(self._sample_penetration(a.lerp(b, t), oracle, colliders) for t in samples)
        blocked = self._cached_segment_ray(a, b, oracle, colliders, params)
        if blocked:
            sample_pen = max(sample_pen, float(params.get("eps_pen", 1.0e-5)))
        if not self._uses_v2(params):
            return sample_pen
        endpoint_pen = max(self._sample_penetration(a, oracle, colliders),
                           self._sample_penetration(b, oracle, colliders))
        return 0.0 if endpoint_pen <= 0.0 and not blocked else sample_pen

    def _segment_blocked(self, a, b, oracle, colliders):
        if self._no_real_colliders(oracle, colliders):
            return False
        if self._segment_ray_blocked(a, b, oracle, colliders):
            return True
        return self._segment_sample_blocked(a, b, oracle, colliders)

    def _segment_blocked_cached(self, a, b, oracle, colliders, params):
        if self._no_real_colliders(oracle, colliders):
            return False
        if self._cached_segment_ray(a, b, oracle, colliders, params):
            return True
        return self._segment_sample_blocked(a, b, oracle, colliders)

    def _segment_sample_blocked(self, a, b, oracle, colliders):
        return any(self._sample_penetration(a.lerp(b, t), oracle, colliders) > 0.0 for t in self._segment_samples())

    def _segment_ray_blocked(self, a, b, oracle, colliders):
        if not hasattr(oracle, "segment_hit_samples"):
            return False
        return bool(tuple(oracle.segment_hit_samples(a, b, colliders)))

    def _cached_segment_ray(self, a, b, oracle, colliders, params):
        return bool(self._cached_segment_hits(a, b, oracle, colliders, params))

    def _cached_segment_hits(self, a, b, oracle, colliders, params):
        if not hasattr(oracle, "segment_hit_samples"):
            return ()
        ctx = self._collision_context(params)
        if ctx is None:
            return tuple(oracle.segment_hit_samples(a, b, colliders))
        key = self._segment_ray_key(a, b, colliders)
        cache = ctx.setdefault("hits", {})
        if key not in cache:
            cache[key] = tuple(oracle.segment_hit_samples(a, b, colliders))
        return cache[key]

    def _segment_ray_key(self, a, b, colliders):
        return self._point_key(a), self._point_key(b), self._colliders_key(colliders)

    def _point_key(self, point):
        return tuple(round(float(v), 6) for v in point)

    def _sample_penetration(self, point, oracle, colliders):
        if self._no_real_colliders(oracle, colliders):
            return 0.0
        _pushed, pen = oracle.push_out_point(point, colliders)
        return float(pen)

    def _no_real_colliders(self, oracle, colliders):
        return not tuple(colliders or ()) and hasattr(oracle, "active_colliders_for_polyline")

    def _segment_sample_correction(self, a, b, pinned, oracle, colliders, a_idx, b_idx, t):
        point = a.lerp(b, t)
        pushed, pen = oracle.push_out_point(point, colliders)
        delta = pushed - point
        if pen <= 0.0 or not self._finite_vector(delta) or delta.length_squared <= 1.0e-18:
            return self._zero_vec(), self._zero_vec(), 0.0
        move_a, move_b = self._sample_endpoint_moves(delta, t, pinned, a_idx, b_idx)
        return move_a, move_b, pen

    def _finite_vector(self, value):
        return all(isfinite(float(component)) for component in value)

    def _sample_endpoint_moves(self, delta, t, pinned, a_idx, b_idx):
        if self._is_pinned(pinned, a_idx) and self._is_pinned(pinned, b_idx):
            return self._zero_vec(), self._zero_vec()
        if self._is_pinned(pinned, a_idx):
            return self._zero_vec(), delta / max(0.05, t)
        if self._is_pinned(pinned, b_idx):
            return delta / max(0.05, 1.0 - t), self._zero_vec()
        scale = (1.0 - t) ** 2 + t ** 2
        return delta * ((1.0 - t) / scale), delta * (t / scale)

    def _apply_segment_moves(self, nodes, pinned, a_idx, b_idx, move_a, move_b):
        if not self._is_pinned(pinned, a_idx):
            nodes[a_idx] = nodes[a_idx] + move_a
        if not self._is_pinned(pinned, b_idx):
            nodes[b_idx] = nodes[b_idx] + move_b

    def _restore_iteration_node(self, nodes, prev_nodes, pinned, index):
        if self._is_pinned(pinned, index):
            return None
        nodes[index] = prev_nodes[index].copy()
        return nodes[index].copy()

    def _is_pinned(self, pinned, index):
        return (index in pinned) if isinstance(pinned, set) else bool(pinned[index])

    def _zero_vec(self):
        return Vector((0.0, 0.0, 0.0))

    def _resample_polyline(self, src, count):
        if not src or count <= 0:
            return []
        if len(src) == 1 or count == 1:
            return [src[0].copy() for _ in range(count)]
        spans, total = self._polyline_spans(src)
        if total <= 1.0e-9:
            return [src[0].copy() for _ in range(count)]
        return self._resample_spans(src, spans, total, count)

    def _resample_spans(self, src, spans, total, count):
        out, segment = [], 0
        for index in range(count):
            target = total * index / float(max(1, count - 1))
            while segment + 2 < len(spans) and spans[segment + 1] < target:
                segment += 1
            out.append(self._span_point(src, spans, segment, target))
        return out

    def _span_point(self, src, spans, segment, target):
        width = max(1.0e-9, spans[segment + 1] - spans[segment])
        return src[segment].lerp(src[segment + 1], (target - spans[segment]) / width)

    def _polyline_spans(self, src):
        spans = [0.0]
        for i in range(len(src) - 1):
            spans.append(spans[-1] + (src[i + 1] - src[i]).length)
        return spans, spans[-1]

    def _max_displacement(self, nodes, prev_nodes):
        md = 0.0
        for i in range(len(nodes)):
            d = (nodes[i] - prev_nodes[i]).length
            if d > md:
                md = d
        return md
