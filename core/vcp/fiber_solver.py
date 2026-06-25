from mathutils import Vector

from ..scp_runtime.common import find_geometry_scp_obj, iter_geometry_mesh_scp_objects
from ..scp_runtime.surface import build_mesh_surface_data
from ..utils import depsgraph_for_scene, scene_for_id
from ..visualization.fiber_sync_helpers import endpoint_world as resolve_fiber_endpoint_world
from .runtime_state import set_fiber_eps_disp, set_fiber_eps_pen, set_fiber_not_converged


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

    def _endpoint_pair(self, root, scene, runtime_registry, fiber_prop):
        a_world = self._endpoint_world(
            root=root,
            scene=scene,
            runtime_registry=runtime_registry,
            parent_id=fiber_prop.a_parent_id,
            attach_param_raw=fiber_prop.a_attach_param,
        )
        b_world = self._endpoint_world(
            root=root,
            scene=scene,
            runtime_registry=runtime_registry,
            parent_id=fiber_prop.b_parent_id,
            attach_param_raw=fiber_prop.b_attach_param,
        )
        return a_world, b_world

    def _runtime_params(self, fiber_prop, bake):
        node_count = max(8, int(fiber_prop.node_count))
        iterations = int(fiber_prop.iterations_bake if bake else fiber_prop.iterations_interactive)
        iterations = max(1, iterations)
        params = {
            "node_count": node_count,
            "iterations": iterations,
            "margin": float(fiber_prop.collision_margin),
            "damping": float(fiber_prop.damping),
            "shorten_strength": max(0.0, min(1.0, float(getattr(fiber_prop, "stretch_stiffness", 0.9)))),
            "bend_strength": max(0.0, min(1.0, float(getattr(fiber_prop, "bend_stiffness", 0.15)))),
            "eps_disp": 1e-5,
            "eps_pen": 1e-5,
        }
        params["min_iters"] = max(8, params["iterations"] // 4)
        return params

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
        return None if not cached else self._resample_nodes(cached, node_count)

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

    def _solver_iteration(self, nodes, prev_nodes, pinned, pin_targets, collider_cache, params, it):
        self._apply_length_shortening(nodes, pinned, params["shorten_strength"])
        if params["bend_strength"] > 0.0 and (it % 2) == 0:
            self._apply_bend_smoothing(nodes, pinned, params["bend_strength"])

        max_pen = self._apply_collision_constraints(
            nodes=nodes,
            pinned=pinned,
            collider_cache=collider_cache,
            margin=params["margin"],
        )
        for idx, pt in pin_targets.items():
            nodes[idx] = pt.copy()

        self._apply_damping(nodes, prev_nodes, pinned, params["damping"])
        max_disp = self._max_displacement(nodes, prev_nodes)
        return max_disp, max_pen

    def solve_points(self, root, fiber_prop, scene, depsgraph, bake=False):
        runtime = self._runtime_registry(root)
        a_world, b_world = self._endpoint_pair(root, scene, runtime, fiber_prop)
        if a_world is None or b_world is None:
            self._mark_failed(fiber_prop)
            return []
        params = self._runtime_params(fiber_prop, bake)
        guide_worlds = self._guide_worlds(root, scene, runtime, fiber_prop)
        colliders = self._surface_colliders(root, scene, runtime)
        collider_cache = self._build_collider_cache(colliders, depsgraph)
        nodes, converged, max_disp, max_pen = self._solve_multilevel(
            fiber_prop, a_world, b_world, guide_worlds, collider_cache, params
        )
        self._store_status(fiber_prop, converged, max_disp, max_pen)
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

    def _runtime_registry(self, root):
        _ = root
        return {}

    def _mark_failed(self, fiber_prop):
        set_fiber_not_converged(fiber_prop, True)
        set_fiber_eps_disp(fiber_prop, 0.0)
        set_fiber_eps_pen(fiber_prop, 0.0)

    def _build_initialized_nodes(self, fiber_prop, a_world, b_world, guide_worlds, params):
        nodes_init, pin_targets = self._build_chain_with_anchors(a_world, b_world, guide_worlds, params["node_count"])
        nodes, pinned = self._initialize_nodes(fiber_prop, nodes_init, pin_targets, params["node_count"])
        return nodes, pinned, pin_targets

    def _solve_multilevel(self, fiber_prop, a_world, b_world, guide_worlds, collider_cache, params):
        counts = self._level_counts(params["node_count"], len(guide_worlds) + 2)
        iters = self._split_iterations(params["iterations"], len(counts))
        seed, converged, max_disp, max_pen = None, False, 0.0, 0.0
        for i, count in enumerate(counts):
            nodes, pinned, targets = self._build_level_nodes(fiber_prop, a_world, b_world, guide_worlds, count, seed)
            active = self._active_colliders(collider_cache, nodes, params["margin"])
            local = self._level_params(params, iters[i])
            converged, max_disp, max_pen = self._run_iterations(nodes, [p.copy() for p in nodes], pinned, targets, active, local)
            seed = nodes
        return ([] if seed is None else seed), converged, max_disp, max_pen

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
        seed_nodes = None if seed is None else self._resample_nodes(seed, node_count)
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

    def _run_iterations(self, nodes, prev_nodes, pinned, pin_targets, collider_cache, params):
        converged = False
        max_disp = 0.0
        max_pen = 0.0
        for it in range(params["iterations"]):
            max_disp, max_pen = self._solver_iteration(nodes, prev_nodes, pinned, pin_targets, collider_cache, params, it)
            prev_nodes = [p.copy() for p in nodes]
            if it >= params["min_iters"] and max_disp < params["eps_disp"] and max_pen < params["eps_pen"]:
                converged = True
                break
        return converged, max_disp, max_pen

    def _store_status(self, fiber_prop, converged, max_disp, max_pen):
        set_fiber_not_converged(fiber_prop, not converged)
        set_fiber_eps_disp(fiber_prop, float(max_disp))
        set_fiber_eps_pen(fiber_prop, float(max_pen))

    def _guide_worlds(self, root, scene, runtime_registry, fiber_prop):
        out = []
        touches = getattr(fiber_prop, "mid_touches", None)
        if not touches:
            return out

        for tp in touches:
            w = self._endpoint_world(
                root=root,
                scene=scene,
                runtime_registry=runtime_registry,
                parent_id=tp.parent_id,
                attach_param_raw=tp.attach_param,
            )
            if w is not None:
                out.append(w)
        return out

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
        add = [int(v) for v in raw]
        for i in range(seg_count):
            edges[i] += add[i]
        leftover = remaining - sum(add)
        if leftover > 0:
            frac = sorted([(raw[i] - int(raw[i]), i) for i in range(seg_count)], reverse=True)
            for k in range(leftover):
                edges[frac[k % len(frac)][1]] += 1
        return edges

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

    def _get_scp_proxy(self, root, scene, scp_id):
        return find_geometry_scp_obj(scene, root.name, scp_id)

    def _shape_param(self, payload):
        try:
            return max(0.0, min(1.0, float(payload)))
        except Exception:
            return 0.0

    def _open_shape_param_mesh(self, parent_obj):
        depsgraph = depsgraph_for_scene(scene_for_id(parent_obj))
        if depsgraph is None:
            return None, None
        obj_eval = parent_obj.evaluated_get(depsgraph)
        return obj_eval, obj_eval.to_mesh()

    def _clear_shape_param_mesh(self, obj_eval, mesh_eval):
        if obj_eval is not None and mesh_eval is not None:
            obj_eval.to_mesh_clear()
        return None

    def _shape_param_vertex(self, mesh_eval, payload):
        if len(mesh_eval.vertices) == 1:
            return mesh_eval.vertices[0].co.copy()
        idx = int(round(payload * float(len(mesh_eval.vertices) - 1)))
        idx = max(0, min(len(mesh_eval.vertices) - 1, idx))
        return mesh_eval.vertices[idx].co.copy()

    def _mesh_local_point_from_shape_param(self, parent_obj, payload):
        if parent_obj is None or parent_obj.type != "MESH" or parent_obj.data is None:
            return None
        obj_eval, mesh_eval = self._open_shape_param_mesh(parent_obj)
        if mesh_eval is None or len(mesh_eval.vertices) == 0:
            return self._clear_shape_param_mesh(obj_eval, mesh_eval)
        try:
            return self._shape_param_vertex(mesh_eval, self._shape_param(payload))
        finally:
            obj_eval.to_mesh_clear()

    def _endpoint_world(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        return resolve_fiber_endpoint_world(root, scene, runtime_registry, parent_id, attach_param_raw)

    def _surface_colliders(self, root, scene, runtime_registry):
        _ = runtime_registry
        out = []
        for obj in iter_geometry_mesh_scp_objects(scene, root.name):
            out.append(obj)
        out.sort(key=lambda o: str(o.get("af_scp_id", "")))
        return out

    def _build_collider_cache(self, colliders, depsgraph):
        cache = []
        for obj in colliders:
            item = self._collider_entry(obj, depsgraph)
            if item is not None:
                cache.append(item)
        return cache

    def _collider_entry(self, obj, depsgraph):
        surface = build_mesh_surface_data(obj, depsgraph)
        if not surface:
            return None
        mn, mx = surface["bounds_world"]
        return {"obj": obj, "bvh": surface["bvh_local"], "m_inv": obj.matrix_world.inverted(), "m3": obj.matrix_world.to_3x3(), "mn": mn, "mx": mx}

    def _point_near_aabb(self, p, mn, mx, margin):
        return (
            (mn.x - margin) <= p.x <= (mx.x + margin)
            and (mn.y - margin) <= p.y <= (mx.y + margin)
            and (mn.z - margin) <= p.z <= (mx.z + margin)
        )

    def _active_colliders(self, collider_cache, nodes, margin):
        if len(collider_cache) <= 1 or not nodes:
            return collider_cache
        mn, mx = self._bounds_from_nodes(nodes)
        active = [c for c in collider_cache if self._aabb_overlap(mn, mx, c["mn"], c["mx"], margin * 2.0)]
        return collider_cache if not active else active

    def _bounds_from_nodes(self, nodes):
        xs, ys, zs = [p.x for p in nodes], [p.y for p in nodes], [p.z for p in nodes]
        return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))

    def _aabb_overlap(self, a_mn, a_mx, b_mn, b_mx, margin):
        return not (
            a_mx.x < (b_mn.x - margin) or b_mx.x < (a_mn.x - margin)
            or a_mx.y < (b_mn.y - margin) or b_mx.y < (a_mn.y - margin)
            or a_mx.z < (b_mn.z - margin) or b_mx.z < (a_mn.z - margin)
        )

    def _apply_length_shortening(self, nodes, pinned, strength):
        n = len(nodes)
        if n < 3 or strength <= 0.0:
            return

        s = max(0.0, min(1.0, strength))
        new_nodes = [p.copy() for p in nodes]
        for i in range(1, n - 1):
            if pinned[i]:
                continue
            target = (nodes[i - 1] + nodes[i + 1]) * 0.5
            new_nodes[i] = nodes[i].lerp(target, s)

        for i in range(1, n - 1):
            if not pinned[i]:
                nodes[i] = new_nodes[i]

    def _apply_bend_smoothing(self, nodes, pinned, bend_stiff):
        n = len(nodes)
        if n < 3 or bend_stiff <= 0.0:
            return

        s = max(0.0, min(1.0, bend_stiff))
        new_nodes = [p.copy() for p in nodes]
        for i in range(1, n - 1):
            if pinned[i]:
                continue
            lap = (nodes[i - 1] + nodes[i + 1]) * 0.5 - nodes[i]
            new_nodes[i] = nodes[i] + lap * s

        for i in range(1, n - 1):
            if not pinned[i]:
                nodes[i] = new_nodes[i]

    def _apply_collision_constraints(self, nodes, pinned, collider_cache, margin):
        max_pen = 0.0
        margin = max(0.0, margin)

        for i in range(1, len(nodes) - 1):
            if pinned[i]:
                continue

            x = nodes[i]
            for c in collider_cache:
                if not self._point_near_aabb(x, c["mn"], c["mx"], margin * 2.0):
                    continue

                x_new, _n_world, pen = self._mesh_push_out_cached(c, x, margin)
                if pen > 0.0:
                    x = x_new
                    max_pen = max(max_pen, pen)

            nodes[i] = x

        return max_pen

    def _mesh_push_out_cached(self, c, x_world, margin):
        bvh = c["bvh"]
        m_inv = c["m_inv"]
        m3 = c["m3"]
        obj = c["obj"]

        x_local = m_inv @ x_world
        hit = bvh.find_nearest(x_local)
        if hit is None or hit[0] is None:
            return x_world, Vector((0.0, 0.0, 1.0)), 0.0

        co, n_local, _face_idx, _dist = hit
        if n_local.length <= 1e-8:
            n_local = Vector((0.0, 0.0, 1.0))
        n_local = n_local.normalized()

        v = x_local - co
        sd = v.dot(n_local)

        if sd >= margin:
            n_world = (m3 @ n_local).normalized()
            return x_world, n_world, 0.0

        pen = margin - sd
        x_local_new = x_local + n_local * pen
        x_world_new = obj.matrix_world @ x_local_new
        n_world = (m3 @ n_local).normalized()
        return x_world_new, n_world, pen

    def _apply_damping(self, nodes, prev_nodes, pinned, damping):
        if damping <= 0.0:
            return
        alpha = max(0.0, min(1.0, 1.0 - damping))
        for i in range(len(nodes)):
            if pinned[i]:
                continue
            nodes[i] = prev_nodes[i].lerp(nodes[i], alpha)

    def _max_displacement(self, nodes, prev_nodes):
        md = 0.0
        for i in range(len(nodes)):
            d = (nodes[i] - prev_nodes[i]).length
            if d > md:
                md = d
        return md
