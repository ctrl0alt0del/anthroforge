from time import perf_counter

from mathutils import Vector

from ..visualization.fiber_sync_helpers import endpoint_world as resolve_fiber_endpoint_world, touch_world as resolve_fiber_touch_world
from .attachment_backend import attachment_issue, attachment_runtime
from .fiber_collision import CollisionOracle
from .fiber_loop import derived_loop_targets, loop_frames, loop_pin_targets, profile_offsets, resample_closed
from .fiber_modes import DERIVED_GENERATION, fiber_root, fibers_by_id, is_derived_loop, is_loop_fiber, loop_anchor_specs
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
        return {"node_count": node_count, "iterations": iterations, "margin": self._default_margin(), "shorten_strength": shorten, "bend_strength": bend, "eps_disp": 1e-5, "eps_pen": 1e-5}

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

    def _solver_iteration(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it):
        self._apply_length_shortening(nodes, pinned, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_bend_smoothing(nodes, pinned, params["bend_strength"])
        max_pen = self._apply_collision_constraints(nodes=nodes, pinned=pinned, oracle=oracle, colliders=colliders, margin=params["margin"])
        self._restore_pins(nodes, pin_targets)
        return self._max_displacement(nodes, prev_nodes), max_pen

    def _restore_pins(self, nodes, pin_targets):
        for idx, pt in pin_targets.items():
            nodes[idx] = pt.copy()

    def solve_points(self, root, fiber_prop, scene, depsgraph, bake=False):
        if is_derived_loop(fiber_prop):
            return self._solve_derived_loop(root, fiber_prop, scene, depsgraph)
        if is_loop_fiber(fiber_prop):
            return self._solve_solved_loop(root, fiber_prop, scene, depsgraph, bake)
        return self._solve_open_fiber(root, fiber_prop, scene, depsgraph, bake)

    def _solve_open_fiber(self, root, fiber_prop, scene, depsgraph, bake):
        runtime, anchors, issue = self._open_anchors(root, scene, depsgraph, fiber_prop)
        if issue:
            return self._invalid_result(fiber_prop, issue)
        params = self._runtime_params(fiber_prop, bake)
        oracle = CollisionOracle(root, scene, depsgraph, params["margin"], self.surface_offset)
        seed, mode, planner_ms, planned = self._plan_seed(oracle, anchors, bake)
        nodes, converged, max_disp, max_pen, active_count, refine_ms = self._refine_solve(fiber_prop, anchors, oracle, params, seed)
        self._store_status(fiber_prop, converged, max_disp, max_pen)
        if not self._preserve_metrics(fiber_prop, bake):
            self._store_metrics(fiber_prop, mode, planner_ms, refine_ms, max(active_count, len(planned)))
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

    def _refine_solve(self, fiber_prop, anchors, oracle, params, seed):
        t0 = perf_counter()
        nodes, converged, max_disp, max_pen, active_count = self._solve_multilevel(fiber_prop, anchors, oracle, params, seed)
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

    def _solve_derived_loop(self, root, fiber_prop, scene, depsgraph, bake=False):
        fiber_map = fibers_by_id(root)
        driver = fiber_root(fiber_prop, fiber_map)
        points = self._driver_loop_points(root, driver, scene, depsgraph, bake)
        if not points:
            return self._failed_derived_loop(fiber_prop)
        self._sync_derived_node_count(fiber_prop, len(points))
        params = self._runtime_params(fiber_prop, False)
        oracle = CollisionOracle(root, scene, depsgraph, params["margin"], self.surface_offset)
        t0 = perf_counter()
        nodes, max_pen, active_count = self._build_derived_loop(fiber_prop, points, oracle)
        self._store_status(fiber_prop, True, 0.0, max_pen)
        self._store_metrics(fiber_prop, DERIVED_GENERATION, 0.0, (perf_counter() - t0) * 1000.0, active_count)
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

    def _failed_derived_loop(self, fiber_prop):
        self._clear_invalid_state(fiber_prop)
        self._mark_failed(fiber_prop)
        return []

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
        prev_nodes = [p.copy() for p in nodes]
        pinned = set(pin_targets)
        for it in range(params["iterations"]):
            max_disp, max_pen = self._cyclic_iteration(nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it)
            prev_nodes = [p.copy() for p in nodes]
            if it >= params["min_iters"] and max_disp < params["eps_disp"] and max_pen < params["eps_pen"]:
                return True, max_disp, max_pen
        return False, max_disp, max_pen

    def _cyclic_iteration(self, nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it):
        self._apply_cyclic_shortening(nodes, pinned, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_cyclic_bend(nodes, pinned, params["bend_strength"])
        max_pen = self._apply_cyclic_collision_constraints(nodes, pinned, oracle, colliders, params["margin"])
        self._restore_pins(nodes, pin_targets)
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

    def _driver_loop_points(self, root, fiber_prop, scene, depsgraph, bake):
        if fiber_prop is None or is_derived_loop(fiber_prop):
            return []
        cached = self._cache.get(fiber_prop.id)
        return [p.copy() for p in cached] if cached and not bake else self.solve_points(root, fiber_prop, scene, depsgraph, bake=bake)

    def _sync_derived_node_count(self, fiber_prop, node_count):
        if int(getattr(fiber_prop, "node_count", 0)) != int(node_count):
            fiber_prop.node_count = int(node_count)

    def _build_derived_loop(self, fiber_prop, driver_points, oracle):
        target = self._derived_target_points(driver_points, fiber_prop)
        return self._smooth_derived_loop(target, oracle)

    def _derived_target_points(self, driver_points, fiber_prop):
        target = derived_loop_targets(driver_points, fiber_prop)
        return target or self._frame_target_points(driver_points, fiber_prop)

    def _frame_target_points(self, driver_points, fiber_prop):
        tangents, normals, binormals = loop_frames(driver_points)
        count = float(max(1, len(driver_points)))
        return [self._derived_point(driver_points[i], normals[i], binormals[i], fiber_prop, i / count) for i in range(len(driver_points))]

    def _derived_point(self, point, normal, binormal, fiber_prop, t):
        offset_u, offset_v = profile_offsets(fiber_prop, t)
        return point + normal * offset_u + binormal * offset_v

    def _smooth_derived_loop(self, points, oracle):
        nodes = [point.copy() for point in points]
        active = oracle.active_colliders_for_polyline(nodes, padding=oracle.margin * 2.0)
        if not active:
            return nodes, 0.0, 0
        return self._relax_derived_loop(nodes, points, oracle, active)

    def _relax_derived_loop(self, nodes, points, oracle, active):
        max_pen = 0.0
        for _ in range(6):
            prev_nodes = [p.copy() for p in nodes]
            self._apply_cyclic_shortening(nodes, set(), 0.12)
            self._apply_spring_to_targets(nodes, points, 0.35)
            max_pen = max(max_pen, self._apply_cyclic_collision_constraints(nodes, set(), oracle, active, oracle.margin))
            self._apply_spring_to_targets(nodes, prev_nodes, 0.05)
        return nodes, max_pen, len(active)

    def _apply_spring_to_targets(self, nodes, targets, strength):
        for i in range(len(nodes)):
            nodes[i] = nodes[i].lerp(targets[i], max(0.0, min(1.0, strength)))

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
        return None if point is None else PlannerAnchor(point.copy(), str(touch.parent_id or ""))

    def _route_anchor(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        point = self._endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)
        return None if point is None else PlannerAnchor(point.copy(), str(parent_id or ""))

    def _plan_seed(self, oracle, anchors, bake):
        if not bake:
            return None, LOCAL_FALLBACK, 0.0, ()
        t0 = perf_counter()
        result = plan_route(oracle, anchors)
        return result.points, result.mode, (perf_counter() - t0) * 1000.0, result.active_ids

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

    def _solve_multilevel(self, fiber_prop, anchors, oracle, params, seed):
        a_world, b_world = anchors[0].point, anchors[-1].point
        guide_worlds = [anchor.point.copy() for anchor in anchors[1:-1]]
        counts = self._level_counts(params["node_count"], len(guide_worlds) + 2)
        iters = self._split_iterations(params["iterations"], len(counts))
        converged, max_disp, max_pen, max_active = False, 0.0, 0.0, 0
        for i, count in enumerate(counts):
            nodes, pinned, targets = self._build_level_nodes(fiber_prop, a_world, b_world, guide_worlds, count, seed)
            active = self._active_colliders(oracle, nodes, params["margin"])
            local = self._level_params(params, iters[i])
            converged, max_disp, max_pen = self._run_iterations(nodes, [p.copy() for p in nodes], pinned, targets, oracle, active, local)
            max_active = max(max_active, len(active))
            seed = nodes
        return ([] if seed is None else seed), converged, max_disp, max_pen, max_active

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
        converged = False
        max_disp = 0.0
        max_pen = 0.0
        for it in range(params["iterations"]):
            max_disp, max_pen = self._solver_iteration(nodes, prev_nodes, pinned, pin_targets, oracle, colliders, params, it)
            prev_nodes = [p.copy() for p in nodes]
            if it >= params["min_iters"] and max_disp < params["eps_disp"] and max_pen < params["eps_pen"]:
                converged = True
                break
        return converged, max_disp, max_pen

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
        return oracle.active_colliders_for_polyline(nodes, padding=oracle.margin * 2.0)

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

    def _apply_collision_constraints(self, nodes, pinned, oracle, colliders, margin):
        max_pen = 0.0
        margin = max(0.0, margin)

        for i in range(1, len(nodes) - 1):
            if pinned[i]:
                continue

            x = nodes[i]
            x, pen = oracle.push_out_point(x, colliders)
            max_pen = max(max_pen, pen)
            nodes[i] = x

        return max_pen

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
