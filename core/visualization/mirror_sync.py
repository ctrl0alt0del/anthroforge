import bpy
from mathutils import Matrix, Vector

from ..utils import get_af_root


def _axis_to_scale(axis: str):
    a = (axis or "X").upper()
    if a == "Y":
        return (1.0, -1.0, 1.0)
    if a == "Z":
        return (1.0, 1.0, -1.0)
    return (-1.0, 1.0, 1.0)


def _mirror_matrix(axis="X", origin=(0.0, 0.0, 0.0)):
    o = origin if isinstance(origin, Vector) else Vector(origin)
    sx, sy, sz = _axis_to_scale(axis)
    s = Matrix.Diagonal((sx, sy, sz, 1.0))
    return Matrix.Translation(o) @ s @ Matrix.Translation(-o)


def mirror_world_matrix(world_matrix, axis="X", origin=(0.0, 0.0, 0.0)):
    return _mirror_matrix(axis=axis, origin=origin) @ world_matrix


class AFMirrorSync:
    def __init__(self, scp_collection_name="AF_VIS", vcp_collection_name="AF_VCP_VIS"):
        self.scp_collection_name = scp_collection_name
        self.vcp_collection_name = vcp_collection_name
        self._syncing = False

    def _get_collection(self, scene, name):
        return scene.collection.children.get(name)

    def _scp_prop_map(self, root):
        return {s.id: s for s in root.af_scp_system.scps}

    def _fiber_prop_map(self, root):
        return {f.id: f for f in root.af_vcp_system.fibers}

    def _explicit_mirror_rule_for_scp(self, scp_prop):
        if not bool(getattr(scp_prop, "mirror_enabled", False)):
            return None
        axis = getattr(scp_prop, "mirror_axis", "X")
        origin = tuple(getattr(scp_prop, "mirror_origin", (0.0, 0.0, 0.0)))
        return axis, origin

    def _effective_rule_for_scp(self, scp_id, scp_map):
        seen = set()
        cur = scp_id
        while cur and cur not in seen:
            seen.add(cur)
            s = scp_map.get(cur)
            if s is None:
                return None
            rule = self._explicit_mirror_rule_for_scp(s)
            if rule is not None:
                return rule
            cur = s.parent_id or ""
        return None

    def _effective_rule_for_fiber(self, fiber_prop, scp_map):
        candidates = []

        if fiber_prop.a_parent_id:
            r = self._effective_rule_for_scp(fiber_prop.a_parent_id, scp_map)
            if r is not None:
                candidates.append(r)

        if fiber_prop.b_parent_id:
            r = self._effective_rule_for_scp(fiber_prop.b_parent_id, scp_map)
            if r is not None:
                candidates.append(r)

        for tp in fiber_prop.mid_touches:
            if tp.parent_id:
                r = self._effective_rule_for_scp(tp.parent_id, scp_map)
                if r is not None:
                    candidates.append(r)

        return candidates[0] if candidates else None

    def _effective_rule_for_muscle(self, muscle_prop, fibers_by_id, scp_map):
        for ref in muscle_prop.fiber_refs:
            f = fibers_by_id.get(ref.fiber_id)
            if f is None:
                continue
            r = self._effective_rule_for_fiber(f, scp_map)
            if r is not None:
                return r
        return None

    def _axis_index(self, axis):
        a = (axis or "X").upper()
        if a == "Y":
            return 1
        if a == "Z":
            return 2
        return 0

    def _intersects_mirror_plane(self, obj, axis="X", origin=(0.0, 0.0, 0.0), eps=1e-6):
        if obj is None or obj.type not in {"MESH", "CURVE"}:
            return False

        ax = self._axis_index(axis)
        o = float(origin[ax]) if hasattr(origin, "__len__") else 0.0
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        vals = [c[ax] - o for c in corners]
        return (min(vals) <= eps and max(vals) >= -eps)

    def _find_source_scp_obj(self, scp_col, root_name, scp_id):
        if scp_col is None:
            return None
        for obj in scp_col.objects:
            if (
                obj.get("af_proxy")
                and not obj.get("af_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
            ):
                return obj
        return None

    def _find_source_fiber_obj(self, vcp_col, root_name, fiber_id):
        if vcp_col is None:
            return None
        for obj in vcp_col.objects:
            if (
                obj.get("af_fiber_proxy")
                and not obj.get("af_fiber_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_fiber_id") == fiber_id
            ):
                return obj
        return None

    def _find_source_muscle_obj(self, vcp_col, root_name, muscle_id, surface):
        if vcp_col is None:
            return None
        for obj in vcp_col.objects:
            if (
                obj.get("af_muscle_proxy")
                and not obj.get("af_muscle_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_muscle_id") == muscle_id
                and obj.get("af_muscle_surface") == surface
            ):
                return obj
        return None

    def _find_mirror_scp_obj(self, scp_col, root_name, source_scp_id):
        if scp_col is None:
            return None
        for obj in scp_col.objects:
            if (
                obj.get("af_proxy")
                and obj.get("af_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_source_scp_id") == source_scp_id
            ):
                return obj
        return None

    def _find_mirror_fiber_obj(self, vcp_col, root_name, source_fiber_id):
        if vcp_col is None:
            return None
        for obj in vcp_col.objects:
            if (
                obj.get("af_fiber_proxy")
                and obj.get("af_fiber_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_source_fiber_id") == source_fiber_id
            ):
                return obj
        return None

    def _find_mirror_muscle_obj(self, vcp_col, root_name, source_muscle_id, surface):
        if vcp_col is None:
            return None
        for obj in vcp_col.objects:
            if (
                obj.get("af_muscle_proxy")
                and obj.get("af_muscle_mirror_proxy")
                and obj.get("af_root_name") == root_name
                and obj.get("af_source_muscle_id") == source_muscle_id
                and obj.get("af_muscle_surface") == surface
            ):
                return obj
        return None

    def _remove_obj(self, obj):
        if obj is None:
            return
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)

    def _ensure_obj_type(self, obj, src_obj):
        if obj is None:
            return None
        if src_obj.type == "MESH" and obj.type != "MESH":
            return None
        if src_obj.type == "CURVE" and obj.type != "CURVE":
            return None
        return obj

    def _create_mirror_from_source(self, collection, src_obj, name):
        if src_obj.type == "MESH":
            data = bpy.data.meshes.new(f"{name}_mesh")
        elif src_obj.type == "CURVE":
            data = bpy.data.curves.new(f"{name}_curve", type="CURVE")
        else:
            return None
        obj = bpy.data.objects.new(name, data)
        collection.objects.link(obj)
        return obj

    def _copy_mesh_data(self, src_obj, dst_obj):
        src = src_obj.data
        verts = [v.co.copy() for v in src.vertices]
        faces = [tuple(p.vertices) for p in src.polygons]
        dst = dst_obj.data
        dst.clear_geometry()
        dst.from_pydata(verts, [], faces)
        dst.update()

    def _copy_curve_data(self, src_obj, dst_obj):
        src = src_obj.data
        dst = dst_obj.data

        dst.dimensions = src.dimensions
        dst.fill_mode = src.fill_mode
        dst.bevel_depth = src.bevel_depth
        dst.bevel_resolution = src.bevel_resolution
        dst.resolution_u = src.resolution_u

        while dst.splines:
            dst.splines.remove(dst.splines[0])

        for s in src.splines:
            ns = dst.splines.new(type=s.type)
            if s.type == "BEZIER":
                ns.bezier_points.add(len(s.bezier_points) - 1)
                for i, bp in enumerate(s.bezier_points):
                    nbp = ns.bezier_points[i]
                    nbp.co = bp.co.copy()
                    nbp.handle_left = bp.handle_left.copy()
                    nbp.handle_right = bp.handle_right.copy()
                    nbp.handle_left_type = bp.handle_left_type
                    nbp.handle_right_type = bp.handle_right_type
                    nbp.radius = bp.radius
                    nbp.tilt = bp.tilt
            else:
                ns.points.add(len(s.points) - 1)
                for i, p in enumerate(s.points):
                    ns.points[i].co = p.co[:]
                    ns.points[i].radius = p.radius
                    ns.points[i].tilt = p.tilt
            ns.use_cyclic_u = s.use_cyclic_u

    def _copy_data(self, src_obj, dst_obj):
        if src_obj.type == "MESH":
            self._copy_mesh_data(src_obj, dst_obj)
        elif src_obj.type == "CURVE":
            self._copy_curve_data(src_obj, dst_obj)

    def _ensure_mirror_material(self, obj, alpha_mult=0.35):
        if obj is None or obj.data is None or not hasattr(obj.data, "materials"):
            return

        src_mat = obj.data.materials[0] if obj.data.materials else None
        base_name = src_mat.name if src_mat else f"AF_MIRROR_{obj.name}"
        mir_name = f"{base_name}_MIR"

        mat = bpy.data.materials.get(mir_name)
        if mat is None:
            mat = bpy.data.materials.new(mir_name)
            mat.use_nodes = False

        if src_mat is not None:
            r, g, b, a = src_mat.diffuse_color
        else:
            r, g, b, a = (0.8, 0.8, 0.8, 1.0)

        mat.diffuse_color = (r, g, b, max(0.05, min(1.0, a * alpha_mult)))

        if hasattr(mat, "blend_method"):
            mat.blend_method = "BLEND"
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = "NONE"
        if hasattr(mat, "show_transparent_back"):
            mat.show_transparent_back = True

        obj.data.materials.clear()
        obj.data.materials.append(mat)

    def _sync_scp_mirrors(self, root, scene, scp_col, scp_map):
        if scp_col is None:
            return

        desired_ids = set()

        for scp_id, scp_prop in scp_map.items():
            rule = self._effective_rule_for_scp(scp_id, scp_map)
            src = self._find_source_scp_obj(scp_col, root.name, scp_id)
            mir = self._find_mirror_scp_obj(scp_col, root.name, scp_id)

            if rule is None or src is None:
                if mir is not None:
                    self._remove_obj(mir)
                continue

            explicit = self._explicit_mirror_rule_for_scp(scp_prop)
            if explicit is not None:
                axis_e, origin_e = explicit
                if self._intersects_mirror_plane(src, axis=axis_e, origin=origin_e):
                    if mir is not None:
                        self._remove_obj(mir)
                    continue

            if mir is None:
                mir = self._create_mirror_from_source(scp_col, src, f"{src.name}_MIR")
            if mir is None:
                continue

            if self._ensure_obj_type(mir, src) is None:
                self._remove_obj(mir)
                mir = self._create_mirror_from_source(scp_col, src, f"{src.name}_MIR")
                if mir is None:
                    continue

            self._copy_data(src, mir)

            axis, origin = rule
            mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)

            mir["af_proxy"] = True
            mir["af_mirror_proxy"] = True
            mir["af_root_name"] = root.name
            mir["af_source_scp_id"] = scp_id
            mir["af_scp_id"] = scp_id

            self._ensure_mirror_material(mir, alpha_mult=0.35)
            desired_ids.add(scp_id)

        for obj in list(scp_col.objects):
            if not obj.get("af_proxy"):
                continue
            if not obj.get("af_mirror_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            sid = obj.get("af_source_scp_id")
            if sid not in desired_ids:
                self._remove_obj(obj)

    def _sync_fiber_mirrors(self, root, vcp_col, scp_map, fibers_by_id):
        if vcp_col is None:
            return

        desired_ids = set()

        for fiber in root.af_vcp_system.fibers:
            rule = self._effective_rule_for_fiber(fiber, scp_map)
            src = self._find_source_fiber_obj(vcp_col, root.name, fiber.id)
            mir = self._find_mirror_fiber_obj(vcp_col, root.name, fiber.id)

            if rule is None or src is None:
                if mir is not None:
                    self._remove_obj(mir)
                continue

            if mir is None:
                mir = self._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
            if mir is None:
                continue

            if self._ensure_obj_type(mir, src) is None:
                self._remove_obj(mir)
                mir = self._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
                if mir is None:
                    continue

            self._copy_data(src, mir)

            axis, origin = rule
            mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)

            mir["af_fiber_proxy"] = True
            mir["af_fiber_mirror_proxy"] = True
            mir["af_root_name"] = root.name
            mir["af_source_fiber_id"] = fiber.id
            mir["af_fiber_id"] = fiber.id

            self._ensure_mirror_material(mir, alpha_mult=0.45)
            desired_ids.add(fiber.id)

        for obj in list(vcp_col.objects):
            if not obj.get("af_fiber_proxy"):
                continue
            if not obj.get("af_fiber_mirror_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            fid = obj.get("af_source_fiber_id")
            if fid not in desired_ids:
                self._remove_obj(obj)

    def _sync_muscle_mirrors(self, root, vcp_col, scp_map, fibers_by_id):
        if vcp_col is None:
            return

        desired_keys = set()

        for muscle in root.af_vcp_system.muscles:
            rule = self._effective_rule_for_muscle(muscle, fibers_by_id, scp_map)

            for surf in ("BASE", "INFL"):
                src = self._find_source_muscle_obj(vcp_col, root.name, muscle.id, surf)
                mir = self._find_mirror_muscle_obj(vcp_col, root.name, muscle.id, surf)

                if rule is None or src is None:
                    if mir is not None:
                        self._remove_obj(mir)
                    continue

                if mir is None:
                    mir = self._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
                if mir is None:
                    continue

                if self._ensure_obj_type(mir, src) is None:
                    self._remove_obj(mir)
                    mir = self._create_mirror_from_source(vcp_col, src, f"{src.name}_MIR")
                    if mir is None:
                        continue

                self._copy_data(src, mir)

                axis, origin = rule
                mir.matrix_world = mirror_world_matrix(src.matrix_world, axis=axis, origin=origin)

                mir["af_muscle_proxy"] = True
                mir["af_muscle_mirror_proxy"] = True
                mir["af_root_name"] = root.name
                mir["af_source_muscle_id"] = muscle.id
                mir["af_muscle_id"] = muscle.id
                mir["af_muscle_surface"] = surf

                self._ensure_mirror_material(mir, alpha_mult=0.40)
                desired_keys.add((muscle.id, surf))

        for obj in list(vcp_col.objects):
            if not obj.get("af_muscle_proxy"):
                continue
            if not obj.get("af_muscle_mirror_proxy"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            key = (obj.get("af_source_muscle_id"), obj.get("af_muscle_surface"))
            if key not in desired_keys:
                self._remove_obj(obj)

    def sync_root_to_scene(self, root=None, scene=None):
        if self._syncing:
            return

        scene = scene or bpy.context.scene
        root = root or get_af_root(scene)
        if root is None:
            return

        self._syncing = True
        try:
            scp_col = self._get_collection(scene, self.scp_collection_name)
            vcp_col = self._get_collection(scene, self.vcp_collection_name)

            scp_map = self._scp_prop_map(root)
            fibers_by_id = self._fiber_prop_map(root)

            self._sync_scp_mirrors(root, scene, scp_col, scp_map)
            self._sync_fiber_mirrors(root, vcp_col, scp_map, fibers_by_id)
            self._sync_muscle_mirrors(root, vcp_col, scp_map, fibers_by_id)
        finally:
            self._syncing = False

    def on_depsgraph_update(self, scene, depsgraph):
        if self._syncing:
            return

        root = get_af_root(scene)
        if root is None:
            return

        relevant = False
        for upd in depsgraph.updates:
            obj = upd.id
            if not isinstance(obj, bpy.types.Object):
                continue
            if obj.get("af_root_name") != root.name:
                continue

            if obj.get("af_proxy") and not obj.get("af_mirror_proxy"):
                relevant = True
                break
            if obj.get("af_fiber_proxy") and not obj.get("af_fiber_mirror_proxy"):
                relevant = True
                break
            if obj.get("af_muscle_proxy") and not obj.get("af_muscle_mirror_proxy"):
                relevant = True
                break
            if obj.get("af_muscle_inflation_ctrl"):
                relevant = True
                break

        if relevant:
            self.sync_root_to_scene(root=root, scene=scene)


_MIRROR_SYNC = None


def register_mirror_sync():
    global _MIRROR_SYNC
    if _MIRROR_SYNC is None:
        _MIRROR_SYNC = AFMirrorSync()

    h = _MIRROR_SYNC.on_depsgraph_update
    if h not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(h)

    return _MIRROR_SYNC


def unregister_mirror_sync():
    global _MIRROR_SYNC
    if _MIRROR_SYNC is None:
        return

    h = _MIRROR_SYNC.on_depsgraph_update
    if h in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(h)

    _MIRROR_SYNC = None
