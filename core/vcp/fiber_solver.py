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

        use_warm_start = bool(getattr(fiber_prop, "use_warm_start", False))
        nodes, pinned = self._init_nodes(
            fiber_id=fiber_prop.id,
            a_world=a_world,
            b_world=b_world,
            node_count=node_count,
            use_warm_start=use_warm_start,
        )
        prev_nodes = [p.copy() for p in nodes]

        rest_total = float(fiber_prop.rest_length)
        if rest_total <= 1e-8:
            rest_total = (b_world - a_world).length

        l0 = rest_total / float(node_count - 1)
        max_total = float(fiber_prop.max_stretch) * rest_total
        max_seg = max_total / float(node_count - 1)

        colliders = self._surface_colliders(root, scene, runtime.registry)
        collider_cache = self._build_collider_cache(colliders, depsgraph)

        stretch_enabled = bool(fiber_prop.stretch_enabled)
        stretch_stiff = float(fiber_prop.stretch_stiffness)
        bend_stiff = float(fiber_prop.bend_stiffness)
        margin = float(fiber_prop.collision_margin)
        damping = float(fiber_prop.damping)

        converged = False
        eps_disp = 1e-4
        eps_pen = 1e-5
        min_iters = max(10, iterations // 4)

        max_disp = 0.0
        max_pen = 0.0

        for it in range(iterations):
            self._apply_stretch_constraints(
                nodes=nodes,
                pinned=pinned,
                l0=l0,
                max_seg=max_seg,
                stretch_enabled=stretch_enabled,
                stiffness=stretch_stiff,
            )

            # bend every second iteration (faster)
            if (it % 2) == 0:
                self._apply_bend_smoothing(nodes, pinned, bend_stiff)

            max_pen = self._apply_collision_constraints(
                nodes=nodes,
                pinned=pinned,
                collider_cache=collider_cache,
                margin=margin,
            )

            # hard pin endpoints
            nodes[0] = a_world.copy()
            nodes[-1] = b_world.copy()

            self._apply_damping(nodes, prev_nodes, pinned, damping)

            max_disp = self._max_displacement(nodes, prev_nodes)
            prev_nodes = [p.copy() for p in nodes]

            if it >= min_iters and max_disp < eps_disp and max_pen < eps_pen:
                converged = True
                break

        fiber_prop.not_converged = not converged
        fiber_prop.last_eps_disp = float(max_disp)
        fiber_prop.last_eps_pen = float(max_pen)

        # always update cache; next solve uses it only if use_warm_start=True
        self._cache[fiber_prop.id] = [p.copy() for p in nodes]
        return nodes

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
