import json
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..registry import SCPRegistry


class FiberSolver:
    """
    PBD-based fiber solver:
    - pinned endpoints
    - stretch constraints (spring to rest + hard stretch cap)
    - bend smoothing
    - collision push-out against SCP proxy meshes
    - cached BVH + AABB broadphase for speed
    - optional warm start per fiber
    """

    def __init__(self, surface_offset=0.002):
        self.surface_offset = float(surface_offset)
        self._cache = {}

    def clear_cache(self, fiber_id=None):
        if fiber_id is None:
            self._cache.clear()
        else:
            self._cache.pop(fiber_id, None)

    # ------------------------------
    # Public
    # ------------------------------

    def solve_points(self, root, fiber_prop, scene, depsgraph, bake=False):
        runtime = SCPRegistry(root)
        runtime.build()

        a_world = self._endpoint_world(
            root=root,
            scene=scene,
            runtime_registry=runtime.registry,
            parent_id=fiber_prop.a_parent_id,
            attach_param_raw=fiber_prop.a_attach_param,
        )
        b_world = self._endpoint_world(
            root=root,
            scene=scene,
            runtime_registry=runtime.registry,
            parent_id=fiber_prop.b_parent_id,
            attach_param_raw=fiber_prop.b_attach_param,
        )

        if a_world is None or b_world is None:
            fiber_prop.not_converged = True
            fiber_prop.last_eps_disp = 0.0
            fiber_prop.last_eps_pen = 0.0
            return []

        node_count = max(8, int(fiber_prop.node_count))
        iterations = int(fiber_prop.iterations_bake if bake else fiber_prop.iterations_interactive)
        iterations = max(1, iterations)

        colliders = self._surface_colliders(root, scene, runtime.registry)
        collider_cache = self._build_collider_cache(colliders, depsgraph)

        stretch_enabled = bool(fiber_prop.stretch_enabled)
        stretch_stiff = float(fiber_prop.stretch_stiffness)
        bend_stiff = float(fiber_prop.bend_stiffness)
        margin = float(fiber_prop.collision_margin)
        damping = float(fiber_prop.damping)
        max_stretch = float(fiber_prop.max_stretch)

        eps_disp = 1e-4
        eps_pen = 1e-5
        min_iters = max(10, iterations // 4)

        guides = self._guide_worlds(root, scene, runtime.registry, fiber_prop)
        anchors = [a_world] + guides + [b_world]
        seg_count = len(anchors) - 1

        if seg_count <= 0:
            fiber_prop.not_converged = True
            fiber_prop.last_eps_disp = 0.0
            fiber_prop.last_eps_pen = 0.0
            return []

        # Distances per anchor span
        seg_dist = []
        total_dist = 0.0
        for i in range(seg_count):
            d = (anchors[i + 1] - anchors[i]).length
            seg_dist.append(d)
            total_dist += d

        if total_dist <= 1e-9:
            total_dist = (b_world - a_world).length
            if total_dist <= 1e-9:
                total_dist = 1.0
            seg_dist = [total_dist / seg_count] * seg_count

        rest_total = float(fiber_prop.rest_length)
        if rest_total <= 1e-8:
            rest_total = total_dist

        # Allocate edges per segment (sum(edges)=node_count-1), min 1 each
        total_edges = max(seg_count, node_count - 1)
        raw_edges = [(total_edges * (d / total_dist)) for d in seg_dist]
        edges = [max(1, int(v)) for v in raw_edges]
        used = sum(edges)

        if used < total_edges:
            frac = sorted(
                [(raw_edges[i] - int(raw_edges[i]), i) for i in range(seg_count)],
                reverse=True
            )
            k = 0
            while used < total_edges:
                edges[frac[k % len(frac)][1]] += 1
                used += 1
                k += 1
        elif used > total_edges:
            frac = sorted(
                [(raw_edges[i] - int(raw_edges[i]), i) for i in range(seg_count)]
            )
            k = 0
            while used > total_edges and k < len(frac) * 4:
                idx = frac[k % len(frac)][1]
                if edges[idx] > 1:
                    edges[idx] -= 1
                    used -= 1
                k += 1

        def solve_segment(p0, p1, seg_edges, seg_rest_total):
            seg_nodes = [p0.lerp(p1, i / float(seg_edges)) for i in range(seg_edges + 1)]
            pinned = [False] * len(seg_nodes)
            pinned[0] = True
            pinned[-1] = True
            prev_nodes = [p.copy() for p in seg_nodes]

            l0 = seg_rest_total / float(max(1, seg_edges))
            max_total = max_stretch * seg_rest_total
            max_seg = max_total / float(max(1, seg_edges))

            converged = False
            max_disp = 0.0
            max_pen = 0.0

            for it in range(iterations):
                self._apply_stretch_constraints(
                    nodes=seg_nodes,
                    pinned=pinned,
                    l0=l0,
                    max_seg=max_seg,
                    stretch_enabled=stretch_enabled,
                    stiffness=stretch_stiff,
                )

                if (it % 2) == 0:
                    self._apply_bend_smoothing(seg_nodes, pinned, bend_stiff)

                max_pen = self._apply_collision_constraints(
                    nodes=seg_nodes,
                    pinned=pinned,
                    collider_cache=collider_cache,
                    margin=margin,
                )

                seg_nodes[0] = p0.copy()
                seg_nodes[-1] = p1.copy()

                self._apply_damping(seg_nodes, prev_nodes, pinned, damping)

                max_disp = self._max_displacement(seg_nodes, prev_nodes)
                prev_nodes = [p.copy() for p in seg_nodes]

                if it >= min_iters and max_disp < eps_disp and max_pen < eps_pen:
                    converged = True
                    break

            return seg_nodes, converged, max_disp, max_pen

        out = []
        all_converged = True
        global_max_disp = 0.0
        global_max_pen = 0.0

        for i in range(seg_count):
            p0 = anchors[i]
            p1 = anchors[i + 1]
            seg_rest = rest_total * (seg_dist[i] / total_dist)

            seg_nodes, ok, md, mp = solve_segment(
                p0=p0,
                p1=p1,
                seg_edges=edges[i],
                seg_rest_total=seg_rest,
            )

            if i == 0:
                out.extend(seg_nodes)
            else:
                out.extend(seg_nodes[1:])  # stitch without duplicating anchor

            all_converged = all_converged and ok
            global_max_disp = max(global_max_disp, md)
            global_max_pen = max(global_max_pen, mp)

        fiber_prop.not_converged = not all_converged
        fiber_prop.last_eps_disp = float(global_max_disp)
        fiber_prop.last_eps_pen = float(global_max_pen)

        self._cache[fiber_prop.id] = [p.copy() for p in out]
        return out



    # ------------------------------
    # Initialization
    # ------------------------------

    def _init_nodes(self, fiber_id, a_world, b_world, node_count, use_warm_start):
        cached = self._cache.get(fiber_id) if use_warm_start else None
        if cached and len(cached) == node_count:
            nodes = [p.copy() for p in cached]
            nodes[0] = a_world.copy()
            nodes[-1] = b_world.copy()
        else:
            nodes = [
                a_world.lerp(b_world, i / float(node_count - 1))
                for i in range(node_count)
            ]

        pinned = [False] * node_count
        pinned[0] = True
        pinned[-1] = True
        return nodes, pinned

    # ------------------------------
    # Endpoint resolve
    # ------------------------------

    def _parse_attach_param(self, raw):
        raw = (raw or "").strip()
        if not raw:
            return 0.0
        try:
            return json.loads(raw)
        except Exception:
            return 0.0

    def _get_scp_proxy(self, root, scene, scp_id):
        for obj in scene.objects:
            if (
                obj.get("af_proxy")
                and obj.get("af_root_name") == root.name
                and obj.get("af_scp_id") == scp_id
            ):
                return obj
        return None

    def _endpoint_world(self, root, scene, runtime_registry, parent_id, attach_param_raw):
        if not parent_id:
            return None

        scp = runtime_registry.get(parent_id)
        if scp is None:
            return None

        proxy = self._get_scp_proxy(root, scene, parent_id)
        if proxy is None:
            return None

        param = self._parse_attach_param(attach_param_raw)
        local = scp.shape.compute_local_point(param)
        return proxy.matrix_world @ local

    # ------------------------------
    # Colliders
    # ------------------------------

    def _surface_colliders(self, root, scene, runtime_registry):
        out = []
        for obj in scene.objects:
            if not obj.get("af_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            if obj.type != "MESH":
                continue

            scp_id = obj.get("af_scp_id")
            scp = runtime_registry.get(scp_id)
            if scp is None:
                continue
            if not getattr(scp.shape, "supports_fiber_collision", True):
                continue

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

    # ------------------------------
    # PBD passes
    # ------------------------------

    def _apply_stretch_constraints(self, nodes, pinned, l0, max_seg, stretch_enabled, stiffness):
        n = len(nodes)
        if n < 2 or stiffness <= 0.0:
            return

        for i in range(n - 1):
            p1 = nodes[i]
            p2 = nodes[i + 1]
            d = p2 - p1
            dist = d.length
            if dist <= 1e-9:
                continue

            # spring to rest length
            target = l0
            c = dist - target
            if abs(c) > 1e-9:
                corr = (c / dist) * d * stiffness

                w1 = 0.0 if pinned[i] else 1.0
                w2 = 0.0 if pinned[i + 1] else 1.0
                wsum = w1 + w2
                if wsum > 0.0:
                    if w1 > 0.0:
                        nodes[i] += corr * (w1 / wsum)
                    if w2 > 0.0:
                        nodes[i + 1] -= corr * (w2 / wsum)

            # hard cap
            if stretch_enabled:
                p1 = nodes[i]
                p2 = nodes[i + 1]
                d = p2 - p1
                dist = d.length
                if dist > max_seg and dist > 1e-9:
                    c_cap = dist - max_seg
                    corr_cap = (c_cap / dist) * d

                    w1 = 0.0 if pinned[i] else 1.0
                    w2 = 0.0 if pinned[i + 1] else 1.0
                    wsum = w1 + w2
                    if wsum > 0.0:
                        if w1 > 0.0:
                            nodes[i] += corr_cap * (w1 / wsum)
                        if w2 > 0.0:
                            nodes[i + 1] -= corr_cap * (w2 / wsum)

    def _apply_bend_smoothing(self, nodes, pinned, bend_stiff):
        n = len(nodes)
        if n < 3 or bend_stiff <= 0.0:
            return

        new_nodes = [p.copy() for p in nodes]
        for i in range(1, n - 1):
            if pinned[i]:
                continue
            lap = (nodes[i - 1] + nodes[i + 1]) * 0.5 - nodes[i]
            new_nodes[i] = nodes[i] + lap * bend_stiff

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

    # ------------------------------
    # Metrics
    # ------------------------------

    def _max_displacement(self, nodes, prev_nodes):
        md = 0.0
        for i in range(len(nodes)):
            d = (nodes[i] - prev_nodes[i]).length
            if d > md:
                md = d
        return md

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

    def _guide_indices(self, node_count, guide_count):
        if guide_count <= 0:
            return []
        idxs = []
        for k in range(guide_count):
            idx = int(round((k + 1) * (node_count - 1) / float(guide_count + 1)))
            idx = max(1, min(node_count - 2, idx))
            while idx in idxs and idx < node_count - 2:
                idx += 1
            while idx in idxs and idx > 1:
                idx -= 1
            if idx not in idxs:
                idxs.append(idx)
        return idxs

    def _apply_guide_constraints(self, nodes, pinned, guide_indices, guide_worlds, stiffness):
        if not guide_indices or not guide_worlds:
            return

        s = max(0.0, min(1.0, float(stiffness)))
        count = min(len(guide_indices), len(guide_worlds))
        for i in range(count):
            idx = guide_indices[i]
            if idx <= 0 or idx >= len(nodes) - 1 or pinned[idx]:
                continue
            g = guide_worlds[i]
            nodes[idx] = g.copy() if s >= 0.999 else nodes[idx].lerp(g, s)

