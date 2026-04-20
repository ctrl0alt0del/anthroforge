import bpy
from mathutils import Vector
from ...shapes.registry import ShapeRegistry
from ...deps.conflict_resolver import resolve_conflict
from ..control_runtime import active_entity_id


class ParallelepipedSCPSyncExtension:
    shape_type = "PARALLELEPIPED"

    def _set_vertex_point(self, scp_prop, vert_index, target_local, *, source="blender_control", payload=None):
        if vert_index < 0 or vert_index >= len(scp_prop.parallelepiped_points):
            return False
        point = scp_prop.parallelepiped_points[vert_index]
        current = (float(point.co[0]), float(point.co[1]), float(point.co[2]))
        incoming = (float(target_local.x), float(target_local.y), float(target_local.z))
        resolved = resolve_conflict(
            entity_type="SCP",
            entity_id=str(getattr(scp_prop, "id", "") or ""),
            aspect=f"geometry.parallelepiped_points[{int(vert_index)}].co",
            source=source,
            current=current,
            incoming=incoming,
            payload=dict(payload or {}),
        )
        try:
            next_value = (float(resolved[0]), float(resolved[1]), float(resolved[2]))
        except Exception:
            next_value = incoming
        if tuple(current) == tuple(next_value):
            return False
        point.co = next_value
        return True

    def _find_vertex_handle(self, vis_col, root_name, scp_id, vert_index):
        for obj in vis_col.objects:
            if (
                obj.get("af_parallelepiped_vert_handle")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
                and int(obj.get("af_parallelepiped_vert_index", -1)) == int(vert_index)
            ):
                return obj
        return None

    def _create_vertex_handle(self, vis_col, root, scp_id, vert_index):
        obj = bpy.data.objects.new(f"AF_{scp_id}_V{vert_index}", None)
        obj.empty_display_type = "CUBE"
        obj.empty_display_size = 0.02
        obj.show_in_front = True
        obj.hide_render = True
        obj["af_parallelepiped_vert_handle"] = True
        obj["af_root_name"] = root.name
        obj["af_scp_id"] = scp_id
        obj["af_parallelepiped_vert_index"] = int(vert_index)
        vis_col.objects.link(obj)
        return obj

    def _active_scp_id(self, root):
        return active_entity_id(root, "SCP")

    def _sync_vertex_handles(self, sync_manager, root, scene, vis_col, scp_prop, live_keys):
        proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_prop.id)
        shape = ShapeRegistry.create_from_prop(scp_prop) if proxy is not None else None
        if proxy is None or shape is None:
            return
        for i, _p in enumerate(scp_prop.parallelepiped_points):
            live_keys.add((scp_prop.id, i))
            h = self._find_vertex_handle(vis_col, root.name, scp_prop.id, i)
            if h is None:
                h = self._create_vertex_handle(vis_col, root, scp_prop.id, i)
            local = shape.compute_local_point(i)
            h.location = proxy.matrix_world @ Vector((local.x, local.y, local.z))

    def _cleanup_stale_vertex_handles(self, vis_col, root_name, live_keys):
        for obj in list(vis_col.objects):
            if not obj.get("af_parallelepiped_vert_handle"):
                continue
            if obj.get("af_root_name") != root_name:
                continue
            key = (obj.get("af_scp_id"), int(obj.get("af_parallelepiped_vert_index", -1)))
            if key not in live_keys:
                bpy.data.objects.remove(obj, do_unlink=True)

    def sync_post(self, sync_manager, root, scene, vis_col):
        live_keys = set()
        active_id = self._active_scp_id(root)

        for scp_prop in root.af_scp_system.scps:
            if scp_prop.id == active_id and scp_prop.shape_type == self.shape_type:
                self._sync_vertex_handles(sync_manager, root, scene, vis_col, scp_prop, live_keys)
        self._cleanup_stale_vertex_handles(vis_col, root.name, live_keys)

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph, control_binding=None):
        if not obj.get("af_parallelepiped_vert_handle"):
            return False, False, None
        scp_id = obj.get("af_scp_id")
        vert_index = int(obj.get("af_parallelepiped_vert_index", -1))
        scp_prop = sync_manager._get_scp_prop_by_id(root, scp_id)
        proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_id)
        if scp_prop is None or proxy is None or scp_prop.shape_type != self.shape_type:
            return True, False, None
        self._activate_scp(root, scp_id)
        if not self._valid_vert_index(scp_prop, vert_index):
            return True, False, None
        space = str(getattr(control_binding, "space", "FINAL") or "FINAL")
        local = self._target_local_point(scp_prop, proxy, obj.location, space=space)
        old = self._point_vec(scp_prop.parallelepiped_points[vert_index])
        if (local - old).length_squared <= 1e-10:
            return True, False, None
        changed = self._set_vertex_point(
            scp_prop,
            vert_index,
            local,
            source="blender_control",
            payload={"vert_index": int(vert_index), "space": str(space)},
        )
        changed |= self._apply_pair_update_if_needed(
            scp_prop,
            proxy,
            obj.location,
            vert_index,
            source="deps_control_mirror_pair",
            payload={"trigger_vert_index": int(vert_index)},
        )
        return True, changed, scp_id if changed else None

    def _activate_scp(self, root, scp_id):
        for i, s in enumerate(root.af_scp_system.scps):
            if s.id == scp_id:
                root.af_scp_system.active_scp_index = i
                return

    def _valid_vert_index(self, scp_prop, vert_index):
        return 0 <= vert_index < len(scp_prop.parallelepiped_points)

    def _point_vec(self, p):
        return Vector((p.co[0], p.co[1], p.co[2]))

    def _target_local_point(self, scp_prop, proxy, world_location, space="FINAL"):
        local_deformed = proxy.matrix_world.inverted() @ world_location
        shape = ShapeRegistry.create_from_prop(scp_prop)
        if shape is None:
            return local_deformed
        return shape.invert_point_from_space(local_deformed, space=space)

    def _apply_pair_update_if_needed(self, scp_prop, proxy, world_location, vert_index, *, source="deps_control_mirror_pair", payload=None):
        shape = ShapeRegistry.create_from_prop(scp_prop)
        if shape is None:
            return False
        pair_update = shape.mirror_pair_update_from_handle(proxy, world_location, vert_index, scp_prop)
        if pair_update is None:
            return False
        pair_index, mirrored_local = pair_update
        if 0 <= pair_index < len(scp_prop.parallelepiped_points):
            return self._set_vertex_point(
                scp_prop,
                pair_index,
                mirrored_local,
                source=source,
                payload=dict(payload or {}, pair_index=int(pair_index)),
            )
        return False
