import bpy
from mathutils import Vector
from ...shapes.registry import ShapeRegistry


class ParallelepipedSCPSyncExtension:
    shape_type = "PARALLELEPIPED"
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
        obj["af_last_sync_loc"] = [0.0, 0.0, 0.0]
        vis_col.objects.link(obj)
        return obj

    def sync_post(self, sync_manager, root, scene, vis_col):
        live_keys = set()
        active_id = ""

        active_obj = bpy.context.view_layer.objects.active if bpy.context and bpy.context.view_layer else None
        if active_obj and active_obj.get("af_root_name") == root.name:
            if active_obj.get("af_parallelepiped_vert_handle") and active_obj.get("af_scp_id"):
                active_id = active_obj.get("af_scp_id")
            elif active_obj.get("af_proxy") and active_obj.get("af_scp_id"):
                active_id = active_obj.get("af_scp_id")

        idx = root.af_scp_system.active_scp_index
        if not active_id and 0 <= idx < len(root.af_scp_system.scps):
            active_id = root.af_scp_system.scps[idx].id

        for scp_prop in root.af_scp_system.scps:
            if scp_prop.id != active_id:
                continue
            if scp_prop.shape_type != self.shape_type:
                continue

            proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_prop.id)
            if proxy is None:
                continue
            shape = ShapeRegistry.create_from_prop(scp_prop)
            if shape is None:
                continue

            for i, _p in enumerate(scp_prop.parallelepiped_points):
                live_keys.add((scp_prop.id, i))
                h = self._find_vertex_handle(vis_col, root.name, scp_prop.id, i)
                if h is None:
                    h = self._create_vertex_handle(vis_col, root, scp_prop.id, i)
                local = shape.compute_local_point(i)
                h.location = proxy.matrix_world @ Vector((local.x, local.y, local.z))
                h["af_last_sync_loc"] = [float(h.location.x), float(h.location.y), float(h.location.z)]

        for obj in list(vis_col.objects):
            if not obj.get("af_parallelepiped_vert_handle"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            key = (obj.get("af_scp_id"), int(obj.get("af_parallelepiped_vert_index", -1)))
            if key not in live_keys:
                bpy.data.objects.remove(obj, do_unlink=True)

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph):
        if not obj.get("af_parallelepiped_vert_handle"):
            return False, False, None

        scp_id = obj.get("af_scp_id")
        vert_index = int(obj.get("af_parallelepiped_vert_index", -1))
        scp_prop = sync_manager._get_scp_prop_by_id(root, scp_id)
        proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_id)
        if scp_prop is None or proxy is None or scp_prop.shape_type != self.shape_type:
            return True, False, None

        for i, s in enumerate(root.af_scp_system.scps):
            if s.id == scp_id:
                root.af_scp_system.active_scp_index = i
                break

        if vert_index < 0 or vert_index >= len(scp_prop.parallelepiped_points):
            return True, False, None

        last = obj.get("af_last_sync_loc")
        if isinstance(last, (list, tuple)) and len(last) == 3:
            last_v = Vector((float(last[0]), float(last[1]), float(last[2])))
            if (obj.location - last_v).length_squared <= 1e-12:
                return True, False, None

        local_deformed = proxy.matrix_world.inverted() @ obj.location
        shape = ShapeRegistry.create_from_prop(scp_prop)
        if shape is not None:
            local = shape.invert_point_deformers(local_deformed)
        else:
            local = local_deformed
        old = Vector((
            scp_prop.parallelepiped_points[vert_index].co[0],
            scp_prop.parallelepiped_points[vert_index].co[1],
            scp_prop.parallelepiped_points[vert_index].co[2],
        ))
        if (local - old).length_squared <= 1e-14:
            return True, False, None

        scp_prop.parallelepiped_points[vert_index].co = (local.x, local.y, local.z)

        if shape is not None:
            pair_update = shape.mirror_pair_update_from_handle(proxy, obj.location, vert_index, scp_prop)
            if pair_update is not None:
                pair_index, mirrored_local = pair_update
                if 0 <= pair_index < len(scp_prop.parallelepiped_points):
                    scp_prop.parallelepiped_points[pair_index].co = (
                        mirrored_local.x,
                        mirrored_local.y,
                        mirrored_local.z,
                    )

        obj["af_last_sync_loc"] = [float(obj.location.x), float(obj.location.y), float(obj.location.z)]

        return True, True, scp_id
