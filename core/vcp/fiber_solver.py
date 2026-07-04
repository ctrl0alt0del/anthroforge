from time import perf_counter

from mathutils import Vector

from ..attachment_codec import fiber_surface_param
from ..visualization.fiber_sync_helpers import endpoint_world as resolve_fiber_endpoint_world, touch_world as resolve_fiber_touch_world
from .attachment_backend import attachment_issue, attachment_runtime
from .fiber_collision import CollisionOracle
from .fiber_loop import loop_pin_targets, resample_closed
from .fiber_modes import is_loop_fiber, loop_anchor_specs
from .fiber_planner import DIRECT, LOCAL_FALLBACK, PlannerAnchor, plan_route
from .runtime_state import (
    fiber_recompute_status,
    fiber_planner_ms,
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
        self._cache = {}

    def clear_cache(self, fiber_id=None):
        if fiber_id is None:
            self._cache.clear()
        else:
            self._cache.pop(fiber_id, None)

    def _default_margin(self):
        return 0.002

    def _runtime_params(self, fiber_prop, bake):
        node_count = max(8, int(fiber_prop.node_count))
        iterations = int(fiber_prop.iterations_bake if bake else fiber_prop.iterations_interactive)
        iterations = max(1, iterations)
        params = self._base_params(fiber_prop, node_count, iterations)
        params["min_iters"] = max(8, params["iterations"] // 4)
        return params

    def _base_params(self, fiber_prop, node_count, iterations):
        shorten, bend = self._strengths(fiber_prop)
        return {
            "node_count": node_count, "iterations": iterations, "margin": self._default_margin(), "shorten_strength": shorten,
            "bend_strength": bend, "segment_collisions": bool(getattr(fiber_prop, "use_segment_collisions", False)), "eps_disp": 1e-5, "eps_pen": 1e-5,
        }

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

    def _seed_or_cache_nodes(self, fiber_prop, nodes_init, node_count, seed):
        if seed is not None:
            return [p.copy() for p in seed]
        cached = self._warm_start_nodes(fiber_prop, node_count)
        return [p.copy() for p in nodes_init] if cached is None else cached

    def _warm_start_nodes(self, fiber_prop, node_count):
        cached = None if not bool(getattr(fiber_prop, "use_warm_start", False)) else self._cache.get(fiber_prop.id)
        return None if not cached else self._resample_polyline(cached, node_count)

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
        self._apply_length_shortening(nodes, pins, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_bend_smoothing(nodes, pins, params["bend_strength"])
        max_pen = self._apply_collision_constraints(nodes=nodes, pinned=pins, oracle=oracle, colliders=colliders, params=params)
        max_pen = self._apply_segment_penalties(max_pen, nodes, pins, oracle, colliders, params)
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
        if is_loop_fiber(fiber_prop):
            return self._solve_solved_loop(root, fiber_prop, scene, depsgraph, bake)
        return self._solve_open_fiber(root, fiber_prop, scene, depsgraph, bake)

    def _solve_open_fiber(self, root, fiber_prop, scene, depsgraph, bake):
        runtime, anchors, issue = self._open_anchors(root, scene, depsgraph, fiber_prop)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        params = self._runtime_params(fiber_prop, bake)
        oracle = CollisionOracle(root, scene, depsgraph, params["margin"], self.surface_offset)
        guides = self._planner_guides(oracle, anchors)
        seed, mode, planner_ms, planned = self._plan_seed(fiber_prop, oracle, anchors, bake)
        if self._preview_planner_route(fiber_prop):
            return self._planner_preview_result(fiber_prop, seed, mode, planner_ms, planned)
        nodes, converged, max_disp, max_pen, active_count, refine_ms = self._refine_solve(fiber_prop, anchors, guides, oracle, params, seed)
        self._store_status(fiber_prop, converged, max_disp, max_pen)
        if not self._preserve_metrics(fiber_prop, bake):
            self._store_metrics(fiber_prop, mode, planner_ms, refine_ms, max(active_count, len(planned)))
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

    def _refine_solve(self, fiber_prop, anchors, guides, oracle, params, seed):
        t0 = perf_counter()
        nodes, converged, max_disp, max_pen, active_count = self._solve_multilevel(fiber_prop, anchors, guides, oracle, params, seed)
        return nodes, converged, max_disp, max_pen, active_count, (perf_counter() - t0) * 1000.0

    def _solve_solved_loop(self, root, fiber_prop, scene, depsgraph, bake):
        runtime, anchors, issue = self._loop_anchors(root, scene, depsgraph, fiber_prop)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        params = self._runtime_params(fiber_prop, bake)
        oracle = CollisionOracle(root, scene, depsgraph, params["margin"], self.surface_offset)
        route, mode, planner_ms, planned = self._loop_seed_route(oracle, anchors, bake)
        nodes, converged, max_disp, max_pen, active_count, refine_ms = self._refine_loop(fiber_prop, anchors, oracle, params, route)
        self._store_status(fiber_prop, converged, max_disp, max_pen)
        if not self._preserve_metrics(fiber_prop, bake):
            self._store_metrics(fiber_prop, mode, planner_ms, refine_ms, max(active_count, len(planned)))
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

    def _loop_route_anchors(self, root, scene, runtime_registry, fiber_prop):
        pairs = loop_anchor_specs(fiber_prop)
        if len(pairs) < 3:
            return None
        anchors = [self._route_anchor(root, scene, runtime_registry, pid, raw) for pid, raw in pairs]
        return None if any(anchor is None for anchor in anchors) else anchors

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
        route = route or [anchor.point.copy() for anchor in anchors]
        nodes = self._loop_nodes(fiber_prop, route, params["node_count"])
        targets = loop_pin_targets(route, [anchor.point.copy() for anchor in anchors], len(nodes))
        active = self._active_colliders(oracle, nodes, params["margin"])
        converged, max_disp, max_pen = self._run_cyclic_iterations(nodes, targets, oracle, active, params)
        return nodes, converged, max_disp, max_pen, len(active)

    def _loop_nodes(self, fiber_prop, route, node_count):
        cached = self._warm_loop_nodes(fiber_prop, node_count)
        return resample_closed(route, node_count) if cached is None else cached

    def _warm_loop_nodes(self, fiber_prop, node_count):
        cached = None if not bool(getattr(fiber_prop, "use_warm_start", False)) else self._cache.get(fiber_prop.id)
        return None if not cached else resample_closed(cached, node_count)

    def _run_cyclic_iterations(self, nodes, pin_targets, oracle, colliders, params):
        prev_nodes, pinned = [p.copy() for p in nodes], set(pin_targets)
        safe = first_safe = self._safe_snapshot(nodes, oracle, colliders, params, cyclic=True, pinned=pinned)
        guards = {}
        for it in range(params["iterations"]):
            colliders = self._active_colliders(oracle, nodes, params["margin"])
            next_guards = {}
            max_disp, max_pen, alpha = self._cyclic_step(nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards)
            guards = next_guards if alpha >= 0.999999 else {}
            prev_nodes, colliders, safe = self._post_iteration_state(nodes, oracle, params, safe, cyclic=True, pinned=pinned)
            if self._iteration_converged(it, max_disp, max_pen, params):
                return True, max_disp, max_pen
            if self._blocked_clear(alpha, max_pen, params):
                return True, max_disp, max_pen
        return self._restore_unconverged(nodes, safe, first_safe, oracle, colliders, params, max_disp, max_pen, cyclic=True)

    def _cyclic_step(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards):
        _ = prev_nodes
        start = [p.copy() for p in nodes]
        candidate = [p.copy() for p in start]
        trial_disp, trial_pen = self._cyclic_iteration(candidate, start, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards)
        alpha, pen = self._accept_candidate(nodes, start, candidate, oracle, params, cyclic=True)
        return self._max_displacement(nodes, start), self._accepted_pen(alpha, pen, trial_pen), alpha

    def _cyclic_iteration(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guard_targets=None, next_guards=None):
        pins = self._effective_pinned(pinned, guard_targets, len(nodes))
        targets = self._effective_pin_targets(pin_targets, guard_targets)
        self._apply_cyclic_shortening(nodes, pins, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_cyclic_bend(nodes, pins, params["bend_strength"])
        max_pen = self._apply_cyclic_collision_constraints(nodes, pins, oracle, colliders, params["margin"])
        max_pen = self._apply_segment_penalties(max_pen, nodes, pins, oracle, colliders, params, cyclic=True)
        self._rollback_segment_introductions(nodes, prev_nodes, pins, oracle, colliders, params, cyclic=True, next_guards=next_guards)
        self._restore_pins(nodes, targets)
        return self._max_displacement(nodes, prev_nodes), max_pen

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

    def _apply_cyclic_collision_constraints(self, nodes, pinned, oracle, colliders, margin):
        max_pen = 0.0
        for i in range(len(nodes)):
            if i in pinned:
                continue
            nodes[i], pen = oracle.push_out_point(nodes[i], colliders)
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
        anchors = [self._route_anchor(root, scene, runtime_registry, fiber_prop.a_parent_id, fiber_prop.a_attach_param)]
        anchors.extend(self._touch_anchor(root, scene, runtime_registry, tp) for tp in getattr(fiber_prop, "mid_touches", ()))
        anchors.append(self._route_anchor(root, scene, runtime_registry, fiber_prop.b_parent_id, fiber_prop.b_attach_param))
        return None if any(anchor is None for anchor in anchors) else anchors

    def _touch_anchor(self, root, scene, runtime_registry, touch):
        point = resolve_fiber_touch_world(root, scene, runtime_registry, touch)
        return None if point is None else PlannerAnchor(point.copy(), str(touch.parent_id or ""), str(touch.attach_param or ""))

    def _route_anchor(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        point = self._endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)
        return None if point is None else PlannerAnchor(point.copy(), str(parent_id or ""), str(attach_param_raw or ""))

    def _planner_guides(self, oracle, anchors):
        guides, last = [], max(0, len(anchors) - 2)
        for i in range(len(anchors) - 1):
            guides.extend(self._segment_guides(oracle, anchors[i], anchors[i + 1]))
            if i < last:
                guides.append(anchors[i + 1].point.copy())
        return guides

    def _segment_guides(self, oracle, start, end):
        route = self._surface_route(oracle, start, end)
        return [] if route is None else [point.copy() for point in route[1:-1]]

    def _surface_route(self, oracle, start, end):
        verts = self._surface_route_vertices(start, end)
        if verts is None:
            return None
        return oracle.surface_path(start.owner_id, verts[0], verts[1])

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
        result = plan_route(oracle, anchors)
        return result.points, result.mode, (perf_counter() - t0) * 1000.0, result.active_ids

    def _interactive_collision_plan(self, fiber_prop):
        return bool(getattr(fiber_prop, "use_segment_collisions", False))

    def _preview_planner_route(self, fiber_prop):
        return bool(getattr(fiber_prop, "preview_planner_route", False))

    def _planner_preview_result(self, fiber_prop, seed, mode, planner_ms, planned):
        points = [] if seed is None else [p.copy() for p in seed]
        self._store_status(fiber_prop, True, 0.0, 0.0)
        self._store_metrics(fiber_prop, mode, planner_ms, 0.0, len(planned))
        self._cache[fiber_prop.id] = [p.copy() for p in points]
        return points

    def _store_metrics(self, fiber_prop, mode, planner_ms, refine_ms, active_count):
        set_fiber_route_mode(fiber_prop, mode)
        set_fiber_planner_ms(fiber_prop, planner_ms)
        set_fiber_refine_ms(fiber_prop, refine_ms)
        set_fiber_active_colliders(fiber_prop, active_count)

    def _preserve_metrics(self, fiber_prop, bake):
        return (not bake) and self._prefer_bake(fiber_prop) and fiber_planner_ms(fiber_prop) > 0.0

    def _prefer_bake(self, fiber_prop):
        try:
            return bool(fiber_prop.get("af_prefer_bake", False))
        except Exception:
            return False

    def _solve_multilevel(self, fiber_prop, anchors, guide_worlds, oracle, params, seed):
        a_world, b_world = anchors[0].point, anchors[-1].point
        params = self._with_endpoint_owners(params, anchors)
        route_seed = None if seed is None else [p.copy() for p in seed]
        counts = self._level_counts(params["node_count"], len(guide_worlds) + 2)
        iters = self._split_iterations(params["iterations"], len(counts))
        converged, max_disp, max_pen, max_active = False, 0.0, 0.0, 0
        for i, count in enumerate(counts):
            nodes, pinned, targets = self._build_level_nodes(fiber_prop, a_world, b_world, guide_worlds, count, seed)
            active = self._active_colliders(oracle, nodes, params["margin"])
            local = self._level_params(params, iters[i])
            converged, max_disp, max_pen = self._run_iterations(nodes, [p.copy() for p in nodes], pinned, targets, oracle, active, local)
            self._restore_seed_if_needed(nodes, route_seed, oracle, local)
            max_active = max(max_active, len(active))
            seed = nodes
        return ([] if seed is None else seed), converged, max_disp, max_pen, max_active

    def _restore_seed_if_needed(self, nodes, seed, oracle, params):
        if seed is None or self._segments_clear(nodes, oracle, self._active_colliders(oracle, nodes, params["margin"]), params, skip_ends=True):
            return
        candidate = self._resample_polyline(seed, len(nodes))
        active = self._active_colliders(oracle, candidate, params["margin"])
        if not self._segments_clear(candidate, oracle, active, params, skip_ends=True):
            return
        for i, point in enumerate(candidate):
            nodes[i] = point.copy()

    def _with_endpoint_owners(self, params, anchors):
        out = dict(params)
        out["endpoint_owners"] = (str(anchors[0].owner_id or ""), str(anchors[-1].owner_id or ""))
        return out

    def _level_counts(self, node_count, anchor_count):
        count = min(node_count, max(8, anchor_count))
        out = [count]
        while out[-1] < node_count:
            out.append(min(node_count, out[-1] * 2))
        return out

    def _split_iterations(self, total, level_count):
        weights = [1 << i for i in range(level_count)]
        scale = float(max(total, level_count)) / float(sum(weights))
        out = [max(1, int(round(w * scale))) for w in weights]
        while sum(out) > total and max(out) > 1:
            out[out.index(max(out))] -= 1
        out[-1] += max(0, total - sum(out))
        return out

    def _build_level_nodes(self, fiber_prop, a_world, b_world, guide_worlds, node_count, seed):
        nodes_init, targets = self._build_chain_with_anchors(a_world, b_world, guide_worlds, node_count)
        seed_nodes = None if seed is None else self._resample_polyline(seed, node_count)
        nodes = self._seed_or_cache_nodes(fiber_prop, nodes_init, node_count, seed_nodes)
        pinned = [False] * node_count
        for idx, pt in targets.items():
            nodes[idx], pinned[idx] = pt.copy(), True
        return nodes, pinned, targets

    def _level_params(self, params, iterations):
        local = dict(params)
        local["iterations"] = max(1, int(iterations))
        local["min_iters"] = max(4, local["iterations"] // 4)
        return local

    def _run_iterations(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params):
        converged, max_disp, max_pen = False, 0.0, 0.0
        colliders = self._active_colliders(oracle, nodes, params["margin"])
        safe = first_safe = self._safe_snapshot(nodes, oracle, colliders, params, skip_ends=True, pinned=pinned)
        guards = {}
        for it in range(params["iterations"]):
            colliders = self._active_colliders(oracle, nodes, params["margin"])
            next_guards = {}
            max_disp, max_pen, alpha = self._open_step(nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards)
            guards = next_guards if alpha >= 0.999999 else {}
            prev_nodes, colliders, safe = self._post_iteration_state(nodes, oracle, params, safe, skip_ends=True, pinned=pinned)
            if self._iteration_converged(it, max_disp, max_pen, params): converged = True; break
            if self._blocked_clear(alpha, max_pen, params): converged = True; break
        safe = self._restore_choice(safe, first_safe, oracle, colliders, params, skip_ends=True)
        self._restore_safe_snapshot(nodes, safe, oracle, colliders, params, skip_ends=True)
        return converged, max_disp, max_pen

    def _restore_unconverged(self, nodes, safe, first_safe, oracle, colliders, params, max_disp, max_pen, cyclic=False, skip_ends=False):
        safe = self._restore_choice(safe, first_safe, oracle, colliders, params, cyclic, skip_ends)
        self._restore_safe_snapshot(nodes, safe, oracle, colliders, params, cyclic, skip_ends)
        return False, max_disp, max_pen

    def _iteration_converged(self, it, max_disp, max_pen, params):
        return it >= params["min_iters"] and max_disp < params["eps_disp"] and max_pen < params["eps_pen"]

    def _blocked_clear(self, alpha, max_pen, params):
        return alpha <= 0.0 and max_pen < params["eps_pen"]

    def _open_step(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards):
        _ = prev_nodes
        start = [p.copy() for p in nodes]
        candidate = [p.copy() for p in start]
        trial_disp, trial_pen = self._solver_iteration(candidate, start, pinned, pin_targets, oracle, colliders, params, it, guards, next_guards)
        alpha, pen = self._accept_candidate(nodes, start, candidate, oracle, params, skip_ends=True)
        return self._max_displacement(nodes, start), self._accepted_pen(alpha, pen, trial_pen), alpha

    def _restore_choice(self, safe, fallback, oracle, colliders, params, cyclic=False, skip_ends=False):
        safe = self._valid_snapshot(safe, oracle, colliders, params, cyclic, skip_ends)
        return safe or self._valid_snapshot(fallback, oracle, colliders, params, cyclic, skip_ends)

    def _valid_snapshot(self, snapshot, oracle, colliders, params, cyclic, skip_ends):
        if snapshot is None:
            return None
        return snapshot if self._segments_clear(snapshot, oracle, colliders, params, cyclic, skip_ends) else None

    def _post_iteration_state(self, nodes, oracle, params, safe, cyclic=False, skip_ends=False, pinned=None):
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
        if self._segments_clear(nodes, oracle, colliders, params, cyclic, skip_ends) and not self._snapshot_better(safe, nodes, cyclic):
            return
        self._copy_nodes(nodes, safe)

    def _snapshot_better(self, candidate, current, cyclic):
        if current is None:
            return True
        return self._path_length(candidate, cyclic) < self._path_length(current, cyclic) - 1.0e-9

    def _snapshot_clear(self, nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
        if not self._segments_clear(nodes, oracle, colliders, params, cyclic, skip_ends):
            return False
        return self._free_nodes_clear(nodes, oracle, colliders, params, cyclic, skip_ends, pinned)

    def _free_nodes_clear(self, nodes, oracle, colliders, params, cyclic, skip_ends, pinned):
        if not params["segment_collisions"]:
            return True
        indices = self._free_node_indices(len(nodes), pinned, cyclic, skip_ends)
        return all(self._sample_penetration(nodes[i], oracle, self._node_colliders(nodes, i, oracle, colliders, params)) <= 0.0 for i in indices)

    def _free_node_indices(self, count, pinned, cyclic, skip_ends):
        for i in range(count):
            if skip_ends and not cyclic and i in (0, count - 1):
                continue
            if pinned is not None and self._is_pinned(pinned, i):
                continue
            yield i

    def _accept_candidate(self, nodes, start, candidate, oracle, params, cyclic=False, skip_ends=False):
        colliders = self._candidate_colliders(oracle, start, candidate, params)
        if self._candidate_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends):
            self._copy_nodes(nodes, candidate)
            return 1.0, 0.0
        return self._backtrack_candidate(nodes, start, candidate, oracle, params, cyclic, skip_ends)

    def _candidate_clear(self, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not self._segments_clear(candidate, oracle, colliders, params, cyclic, skip_ends):
            return False
        if not self._moved_points_clear(candidate, start, candidate, oracle, colliders, params, cyclic, skip_ends):
            return False
        if not self._candidate_start_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends):
            return True
        return self._sweep_clear(start, candidate, oracle, colliders, params, cyclic, skip_ends)

    def _candidate_start_clear(self, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not self._segments_clear(start, oracle, colliders, params, cyclic, skip_ends):
            return False
        return self._moved_points_clear(start, start, candidate, oracle, colliders, params, cyclic, skip_ends)

    def _backtrack_candidate(self, nodes, start, candidate, oracle, params, cyclic, skip_ends):
        colliders = self._candidate_colliders(oracle, start, candidate, params)
        start_pen = self._state_penetration(start, oracle, colliders, params, cyclic, skip_ends)
        best = (start_pen, 0.0, start)
        for alpha in self._backtrack_alphas():
            trial = self._interpolate_nodes(start, candidate, alpha)
            if self._candidate_clear(start, trial, oracle, colliders, params, cyclic, skip_ends):
                self._copy_nodes(nodes, trial)
                return alpha, 0.0
            best = self._best_penalty_choice(best, trial, alpha, oracle, colliders, params, cyclic, skip_ends)
        return self._use_best_candidate(nodes, best, start_pen)

    def _best_penalty_choice(self, best, trial, alpha, oracle, colliders, params, cyclic, skip_ends):
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
        return all(self._node_path_clear(start, candidate, i, oracle, colliders, params) for i in self._moving_node_indices(start, candidate, cyclic, skip_ends))

    def _node_path_clear(self, start, candidate, index, oracle, colliders, params):
        cols = self._node_colliders(candidate, index, oracle, colliders, params)
        return self._segment_penetration(start[index], candidate[index], oracle, cols) <= 0.0

    def _moved_points_clear(self, points, start, candidate, oracle, colliders, params, cyclic, skip_ends):
        if not params["segment_collisions"]:
            return True
        values = self._moving_node_indices(start, candidate, cyclic, skip_ends)
        return all(self._sample_penetration(points[i], oracle, self._node_colliders(points, i, oracle, colliders, params)) <= 0.0 for i in values)

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
        pairs = self._clear_segment_pairs(len(nodes), cyclic, skip_ends)
        return all(self._pair_penetration(nodes, a, b, oracle, colliders, params) <= 0.0 for a, b in pairs)

    def _state_penetration(self, nodes, oracle, colliders, params, cyclic=False, skip_ends=False):
        if not params["segment_collisions"]:
            return 0.0
        pairs = self._clear_segment_pairs(len(nodes), cyclic, skip_ends)
        return max((self._pair_penetration(nodes, a, b, oracle, colliders, params) for a, b in pairs), default=0.0)

    def _pair_penetration(self, nodes, a_idx, b_idx, oracle, colliders, params):
        cols = self._pair_colliders(nodes, a_idx, b_idx, oracle, colliders, params)
        return self._segment_penetration(nodes[a_idx], nodes[b_idx], oracle, cols)

    def _pair_colliders(self, nodes, a_idx, b_idx, oracle, colliders, params):
        start, end = self._owner_zone_limits(nodes, oracle, colliders, params)
        return tuple(c for c in colliders if self._pair_collider_allowed(c, a_idx, b_idx, start, end))

    def _node_colliders(self, nodes, index, oracle, colliders, params):
        start, end = self._owner_zone_limits(nodes, oracle, colliders, params)
        return tuple(c for c in colliders if self._node_collider_allowed(c, index, start, end))

    def _pair_collider_allowed(self, collider, a_idx, b_idx, start, end):
        sid, low, high = str(collider["sid"]), min(a_idx, b_idx), max(a_idx, b_idx)
        if start[0] and sid == start[0] and low < start[1]:
            return False
        return not (end[0] and sid == end[0] and high >= end[1])

    def _node_collider_allowed(self, collider, index, start, end):
        sid = str(collider["sid"])
        if start[0] and sid == start[0] and index < start[1]:
            return False
        return not (end[0] and sid == end[0] and index >= end[1])

    def _owner_zone_limits(self, nodes, oracle, colliders, params):
        owners = tuple(params.get("endpoint_owners", ("", "")) or ("", ""))
        start = self._owner_start_limit(nodes, oracle, self._collider_by_sid(colliders, owners[0]))
        end = self._owner_end_limit(nodes, oracle, self._collider_by_sid(colliders, owners[1]))
        return (owners[0], start), (owners[1], end)

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
        return oracle.active_colliders_for_polyline(nodes, padding=max(0.05, oracle.clearance * 2.0, oracle.margin * 4.0))

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
        for i in range(1, len(nodes) - 1):
            if pinned[i]:
                continue
            x, pen = oracle.push_out_point(nodes[i], self._node_colliders(nodes, i, oracle, colliders, params))
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
        if self._segment_introduced_collision(nodes, prev_nodes, oracle, colliders, params, a_idx, b_idx):
            restored = self._restore_iteration_node(nodes, prev_nodes, pinned, b_idx)
            self._record_guard_target(next_guards, b_idx, restored)

    def _record_guard_target(self, next_guards, index, point):
        if next_guards is not None and point is not None:
            next_guards[int(index)] = point.copy()

    def _segment_introduced_collision(self, nodes, prev_nodes, oracle, colliders, params, a_idx, b_idx):
        before = self._pair_penetration(prev_nodes, a_idx, b_idx, oracle, colliders, params)
        after = self._pair_penetration(nodes, a_idx, b_idx, oracle, colliders, params)
        return before <= 0.0 and after > 0.0

    def _apply_segment_collision_constraints(self, nodes, pinned, oracle, colliders, params, cyclic=False):
        pairs = self._segment_pairs(len(nodes), cyclic)
        max_pen = 0.0
        for a_idx, b_idx in pairs:
            cols = self._pair_colliders(nodes, a_idx, b_idx, oracle, colliders, params)
            max_pen = max(max_pen, self._segment_penalty(nodes, pinned, oracle, cols, a_idx, b_idx))
        return max_pen

    def _segment_pairs(self, count, cyclic):
        pairs = [(i, i + 1) for i in range(max(0, count - 1))]
        return pairs + ([(count - 1, 0)] if cyclic and count > 2 else [])

    def _segment_penalty(self, nodes, pinned, oracle, colliders, a_idx, b_idx):
        move_a, move_b, max_pen = self._zero_vec(), self._zero_vec(), 0.0
        for t in self._segment_samples_for(nodes[a_idx], nodes[b_idx], oracle, colliders):
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

    def _merged_segment_samples(self, base, hits):
        values = {round(float(t), 6) for t in base}
        values.update(round(float(t), 6) for t in tuple(hits or ()) if 0.0 < float(t) < 1.0)
        return tuple(sorted(values))

    def _segment_penetration(self, a, b, oracle, colliders):
        return max(self._sample_penetration(a.lerp(b, t), oracle, colliders) for t in self._segment_samples_for(a, b, oracle, colliders))

    def _sample_penetration(self, point, oracle, colliders):
        _pushed, pen = oracle.push_out_point(point, colliders)
        return float(pen)

    def _segment_sample_correction(self, a, b, pinned, oracle, colliders, a_idx, b_idx, t):
        point = a.lerp(b, t)
        pushed, pen = oracle.push_out_point(point, colliders)
        delta = pushed - point
        if pen <= 0.0 or delta.length_squared <= 1.0e-18:
            return self._zero_vec(), self._zero_vec(), 0.0
        move_a, move_b = self._sample_endpoint_moves(delta, t, pinned, a_idx, b_idx)
        return move_a, move_b, pen

    def _sample_endpoint_moves(self, delta, t, pinned, a_idx, b_idx):
        if self._is_pinned(pinned, a_idx) and self._is_pinned(pinned, b_idx):
            return self._zero_vec(), self._zero_vec()
        if self._is_pinned(pinned, a_idx):
            return self._zero_vec(), delta / max(1.0e-6, t)
        if self._is_pinned(pinned, b_idx):
            return delta / max(1.0e-6, 1.0 - t), self._zero_vec()
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
        return [self._polyline_point(src, spans, total, i, count) for i in range(count)]

    def _polyline_spans(self, src):
        spans = [0.0]
        for i in range(len(src) - 1):
            spans.append(spans[-1] + (src[i + 1] - src[i]).length)
        return spans, spans[-1]

    def _polyline_point(self, src, spans, total, index, count):
        target = 0.0 if count <= 1 else total * index / float(count - 1)
        seg = next((i for i in range(len(spans) - 1) if spans[i + 1] >= target), len(spans) - 2)
        span = max(1.0e-9, spans[seg + 1] - spans[seg])
        return src[seg].lerp(src[seg + 1], (target - spans[seg]) / span)

    def _max_displacement(self, nodes, prev_nodes):
        md = 0.0
        for i in range(len(nodes)):
            d = (nodes[i] - prev_nodes[i]).length
            if d > md:
                md = d
        return md
