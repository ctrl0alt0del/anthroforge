from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..attachment_codec import parse_fiber_attach_param
from ..scp_runtime.common import find_geometry_scp_obj, iter_geometry_mesh_scp_objects
from ..utils import depsgraph_for_scene, scene_for_id


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
        use_warm_start = bool(getattr(fiber_prop, "use_warm_start", False))
        cached = self._cache.get(fiber_prop.id) if use_warm_start else None
        if cached and len(cached) == node_count:
            nodes = [p.copy() for p in cached]
            for idx, pt in pin_targets.items():
                nodes[idx] = pt.copy()
        else:
            nodes = [p.copy() for p in nodes_init]

        pinned = [False] * node_count
        for idx in pin_targets.keys():
            pinned[idx] = True
        return nodes, pinned

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
        nodes, pinned, pin_targets = self._build_initialized_nodes(fiber_prop, a_world, b_world, guide_worlds, params)
        prev_nodes = [p.copy() for p in nodes]
        colliders = self._surface_colliders(root, scene, runtime)
        collider_cache = self._build_collider_cache(colliders, depsgraph)
        converged, max_disp, max_pen = self._run_iterations(nodes, prev_nodes, pinned, pin_targets, collider_cache, params)
        self._store_status(fiber_prop, converged, max_disp, max_pen)
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

    def _runtime_registry(self, root):
        _ = root
        return {}

    def _mark_failed(self, fiber_prop):
        fiber_prop.not_converged = True
        fiber_prop.last_eps_disp = 0.0
        fiber_prop.last_eps_pen = 0.0

    def _build_initialized_nodes(self, fiber_prop, a_world, b_world, guide_worlds, params):
        nodes_init, pin_targets = self._build_chain_with_anchors(a_world, b_world, guide_worlds, params["node_count"])
        nodes, pinned = self._initialize_nodes(fiber_prop, nodes_init, pin_targets, params["node_count"])
        return nodes, pinned, pin_targets

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
        fiber_prop.not_converged = not converged
        fiber_prop.last_eps_disp = float(max_disp)
        fiber_prop.last_eps_pen = float(max_pen)

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
        _ = runtime_registry
        if not parent_id:
            return None

        proxy = self._get_scp_proxy(root, scene, parent_id)
        if proxy is None:
            return None

        mode, payload = parse_fiber_attach_param(attach_param_raw)
        if mode == "mesh_anchor":
            local = payload
        elif mode == "shape_param_v1":
            local = self._mesh_local_point_from_shape_param(proxy, payload)
        else:
            return None

        if local is None:
            return None
        return proxy.matrix_world @ local

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
            bvh = BVHTree.FromObject(obj, depsgraph)
            if bvh is None:
                continue

            corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            mn = Vector((
                min(v.x for v in corners),
                min(v.y for v in corners),
                min(v.z for v in corners),
            ))
            mx = Vector((
                max(v.x for v in corners),
                max(v.y for v in corners),
                max(v.z for v in corners),
            ))

            cache.append({
                "obj": obj,
                "bvh": bvh,
                "m_inv": obj.matrix_world.inverted(),
                "m3": obj.matrix_world.to_3x3(),
                "mn": mn,
                "mx": mx,
            })
        return cache

    def _point_near_aabb(self, p, mn, mx, margin):
        return (
            (mn.x - margin) <= p.x <= (mx.x + margin)
            and (mn.y - margin) <= p.y <= (mx.y + margin)
            and (mn.z - margin) <= p.z <= (mx.z + margin)
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
