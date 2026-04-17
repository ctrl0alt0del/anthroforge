import bpy
from mathutils import Vector
from ...shapes.state_codec import set_deformer_param_patch
from ...shapes.registry import ShapeRegistry
from ...deps.conflict_resolver import resolve_conflict
from ..control_runtime import active_entity_id


class EllipsoidSCPSyncExtension:
    shape_type = "ELLIPSOID"

    def _find_clip_handle(self, vis_col, root_name, scp_id, clip_index):
        for obj in vis_col.objects:
            if (
                obj.get("af_ellipsoid_clip_handle")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
                and int(obj.get("af_ellipsoid_clip_index", -1)) == int(clip_index)
            ):
                return obj
        return None

    def _create_clip_handle(self, vis_col, root, scp_id, clip_index):
        mesh = bpy.data.meshes.new(f"AF_{scp_id}_CLIP{clip_index}_mesh")
        s = 0.35
        verts = [(-s, -s, 0.0), (s, -s, 0.0), (s, s, 0.0), (-s, s, 0.0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        obj = bpy.data.objects.new(f"AF_{scp_id}_CLIP{clip_index}", mesh)
        obj.display_type = "WIRE"
        obj.show_in_front = True
        obj.hide_render = True
        obj["af_ellipsoid_clip_handle"] = True
        obj["af_root_name"] = root.name
        obj["af_scp_id"] = scp_id
        obj["af_ellipsoid_clip_index"] = int(clip_index)
        obj["af_no_parent"] = True
        vis_col.objects.link(obj)
        return obj

    def _local_plane_to_world(self, proxy, n_local, off_local):
        n = n_local.copy()
        if n.length <= 1e-9:
            n = Vector((1.0, 0.0, 0.0))
        n.normalize()

        p3 = proxy.matrix_world.to_3x3()
        inv = p3.inverted_safe()
        # Normal transform: (M^-1)^T * n_local
        n_world = (inv.transposed() @ n).normalized()

        p_local = n * float(off_local)
        p_world = proxy.matrix_world @ p_local
        return n_world, p_world

    def _world_plane_to_local(self, proxy, n_world, p_world):
        n = n_world.copy()
        if n.length <= 1e-9:
            n = Vector((1.0, 0.0, 0.0))
        n.normalize()

        p3 = proxy.matrix_world.to_3x3()
        # Local normal transform: M^T * n_world
        n_local = (p3.transposed() @ n)
        if n_local.length <= 1e-9:
            n_local = Vector((1.0, 0.0, 0.0))
        n_local.normalize()

        p_local = proxy.matrix_world.inverted() @ p_world
        off_local = float(n_local.dot(p_local))
        return n_local, off_local

    def _remove_obj(self, obj):
        if obj is None:
            return
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)

    def _is_user_transform_active(self):
        try:
            wm = bpy.context.window_manager
            ops = getattr(wm, "operators", None) or []
            for op in reversed(list(ops)):
                bid = getattr(op, "bl_idname", "") or ""
                if bid in ("TRANSFORM_OT_translate", "TRANSFORM_OT_rotate", "TRANSFORM_OT_trackball"):
                    return True
                if bid == "TRANSFORM_OT_transform":
                    mode = str(getattr(getattr(op, "properties", None), "mode", "") or "")
                    if mode in ("TRANSLATION", "ROTATION"):
                        return True
            return False
        except Exception:
            return False

    def _active_scp_id(self, root):
        return active_entity_id(root, "SCP")

    def _is_editing_handle(self, handle):
        active_obj = bpy.context.view_layer.objects.active if bpy.context and bpy.context.view_layer else None
        return active_obj is not None and active_obj == handle and self._is_user_transform_active()

    def _sync_clip_handle(self, sync_manager, root, scene, vis_col, scp_prop, clip_index, avg_r, live):
        live.add((scp_prop.id, clip_index))
        h = self._find_clip_handle(vis_col, root.name, scp_prop.id, clip_index)
        if h is None:
            h = self._create_clip_handle(vis_col, root, scp_prop.id, clip_index)
        h.scale = (avg_r, avg_r, avg_r)
        if self._is_editing_handle(h):
            return
        n = Vector(getattr(scp_prop, f"ellipsoid_clip{clip_index}_normal", (1.0, 0.0, 0.0)))
        n = n.normalized() if n.length > 1e-9 else Vector((1.0, 0.0, 0.0))
        off = float(getattr(scp_prop, f"ellipsoid_clip{clip_index}_offset", 0.0))
        n_world, p_world = self._local_plane_to_world(sync_manager._find_proxy_in_scene(scene, root.name, scp_prop.id), n, off)
        h.location = p_world
        h.rotation_mode = "QUATERNION"
        h.rotation_quaternion = n_world.to_track_quat("Z", "Y")

    def _cleanup_stale_handles(self, vis_col, root_name, live):
        for obj in list(vis_col.objects):
            if not obj.get("af_ellipsoid_clip_handle"):
                continue
            if obj.get("af_root_name") != root_name:
                continue
            key = (obj.get("af_scp_id"), int(obj.get("af_ellipsoid_clip_index", -1)))
            if key not in live:
                self._remove_obj(obj)

    def sync_post(self, sync_manager, root, scene, vis_col):
        active_id = self._active_scp_id(root)
        live = set()

        for scp_prop in root.af_scp_system.scps:
            if scp_prop.id != active_id or scp_prop.shape_type != self.shape_type:
                continue

            proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_prop.id)
            if proxy is None:
                continue
            if not bool(getattr(scp_prop, "ellipsoid_clip_enabled", False)):
                continue
            shape = ShapeRegistry.create_from_prop(scp_prop)
            if shape is None:
                continue
            avg_r = max(0.1, (shape.radii[0] + shape.radii[1] + shape.radii[2]) / 3.0)
            for clip_index in (1, 2):
                if not bool(getattr(scp_prop, f"ellipsoid_clip{clip_index}_enabled", False)):
                    continue
                self._sync_clip_handle(sync_manager, root, scene, vis_col, scp_prop, clip_index, avg_r, live)
        self._cleanup_stale_handles(vis_col, root.name, live)

    def _activate_scp_in_tree(self, root, scp_id):
        for i, s in enumerate(root.af_scp_system.scps):
            if s.id == scp_id:
                root.af_scp_system.active_scp_index = i
                return

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph, control_binding=None):
        if not obj.get("af_ellipsoid_clip_handle"):
            return False, False, None

        scp_id = obj.get("af_scp_id")
        clip_index = int(obj.get("af_ellipsoid_clip_index", -1))
        if clip_index not in (1, 2):
            return True, False, None

        scp_prop = sync_manager._get_scp_prop_by_id(root, scp_id)
        proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_id)
        if scp_prop is None or proxy is None or scp_prop.shape_type != self.shape_type:
            return True, False, None
        self._activate_scp_in_tree(root, scp_id)
        mw = obj.matrix_world.copy()
        n = (mw.to_quaternion() @ Vector((0.0, 0.0, 1.0)))
        if n.length <= 1e-9:
            n = Vector((1.0, 0.0, 0.0))
        n.normalize()
        n_local, off = self._world_plane_to_local(proxy, n, mw.translation)
        changed = self._write_clip_props(
            scp_prop,
            clip_index,
            n_local,
            off,
            source="blender_control",
            payload={"clip_index": int(clip_index)},
        )
        return True, changed, scp_id if changed else None

    def _resolve_clip_value(self, scp_prop, aspect, current, incoming, *, source="blender_control", payload=None):
        resolved = resolve_conflict(
            entity_type="SCP",
            entity_id=str(getattr(scp_prop, "id", "") or ""),
            aspect=str(aspect or ""),
            source=source,
            current=current,
            incoming=incoming,
            payload=dict(payload or {}),
        )
        return resolved

    def _write_clip_props(self, scp_prop, clip_index, n_local, off, *, source="blender_control", payload=None):
        changed = False

        current_enabled = bool(getattr(scp_prop, "ellipsoid_clip_enabled", False))
        next_enabled_raw = self._resolve_clip_value(
            scp_prop,
            "geometry.ellipsoid.clip.enabled",
            current_enabled,
            True,
            source=source,
            payload=payload,
        )
        next_enabled = bool(next_enabled_raw)
        if current_enabled != next_enabled:
            setattr(scp_prop, "ellipsoid_clip_enabled", next_enabled)
            changed = True

        clip_enabled_attr = f"ellipsoid_clip{clip_index}_enabled"
        current_clip_enabled = bool(getattr(scp_prop, clip_enabled_attr, False))
        next_clip_enabled_raw = self._resolve_clip_value(
            scp_prop,
            f"geometry.ellipsoid.clip[{int(clip_index)}].enabled",
            current_clip_enabled,
            True,
            source=source,
            payload=payload,
        )
        next_clip_enabled = bool(next_clip_enabled_raw)
        if current_clip_enabled != next_clip_enabled:
            setattr(scp_prop, clip_enabled_attr, next_clip_enabled)
            changed = True

        incoming_normal = (float(n_local.x), float(n_local.y), float(n_local.z))
        current_normal = tuple(getattr(scp_prop, f"ellipsoid_clip{clip_index}_normal", (1.0, 0.0, 0.0)))
        next_normal_raw = self._resolve_clip_value(
            scp_prop,
            f"geometry.ellipsoid.clip[{int(clip_index)}].normal",
            current_normal,
            incoming_normal,
            source=source,
            payload=payload,
        )
        try:
            next_normal = (
                float(next_normal_raw[0]),
                float(next_normal_raw[1]),
                float(next_normal_raw[2]),
            )
        except Exception:
            next_normal = incoming_normal
        if tuple(current_normal) != tuple(next_normal):
            setattr(scp_prop, f"ellipsoid_clip{clip_index}_normal", next_normal)
            changed = True

        incoming_offset = float(off)
        current_offset = float(getattr(scp_prop, f"ellipsoid_clip{clip_index}_offset", 0.0))
        next_offset_raw = self._resolve_clip_value(
            scp_prop,
            f"geometry.ellipsoid.clip[{int(clip_index)}].offset",
            current_offset,
            incoming_offset,
            source=source,
            payload=payload,
        )
        try:
            next_offset = float(next_offset_raw)
        except Exception:
            next_offset = incoming_offset
        if abs(next_offset - current_offset) > 1e-10:
            setattr(scp_prop, f"ellipsoid_clip{clip_index}_offset", next_offset)
            changed = True

        set_deformer_param_patch(scp_prop, "ellipsoid_clip", "enabled", bool(next_enabled))
        set_deformer_param_patch(scp_prop, "ellipsoid_clip", f"clip{clip_index}_enabled", bool(next_clip_enabled))
        set_deformer_param_patch(scp_prop, "ellipsoid_clip", f"clip{clip_index}_normal", tuple(next_normal))
        set_deformer_param_patch(scp_prop, "ellipsoid_clip", f"clip{clip_index}_offset", float(next_offset))
        return changed
