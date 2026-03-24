import bpy
from mathutils import Vector
from ...shapes.registry import ShapeRegistry


class CurveSCPSyncExtension:
    shape_type = "CURVE"

    def _find_curve_point_handle(self, vis_col, root_name, scp_id, point_index):
        for obj in vis_col.objects:
            if (
                obj.get("af_curve_point_handle")
                and obj.get("af_root_name") == root_name
                and obj.get("af_scp_id") == scp_id
                and int(obj.get("af_curve_point_index", -1)) == int(point_index)
            ):
                return obj
        return None

    def _create_curve_point_handle(self, vis_col, root, scp_id, point_index):
        obj = bpy.data.objects.new(f"AF_{scp_id}_CP{point_index}", None)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = 0.02
        obj.show_in_front = True
        obj.hide_render = True
        obj["af_curve_point_handle"] = True
        obj["af_root_name"] = root.name
        obj["af_scp_id"] = scp_id
        obj["af_curve_point_index"] = int(point_index)
        vis_col.objects.link(obj)
        return obj

    def _apply_curve_proportional_delta(self, scp_prop, center_idx, center_new_local):
        points = scp_prop.curve_points
        n = len(points)
        if not (0 <= center_idx < n):
            return False

        old_center = Vector((points[center_idx].co[0], points[center_idx].co[1], points[center_idx].co[2]))
        delta = center_new_local - old_center
        if delta.length_squared <= 1e-14:
            return False

        points[center_idx].co = (center_new_local.x, center_new_local.y, center_new_local.z)

        if not bool(getattr(scp_prop, "curve_proportional_enabled", False)):
            return True

        radius = max(0.001, float(getattr(scp_prop, "curve_proportional_radius", 2.0)))
        strength = max(0.0, min(1.0, float(getattr(scp_prop, "curve_proportional_strength", 0.65))))
        if strength <= 0.0:
            return True

        for i in range(n):
            if i == center_idx:
                continue
            d = abs(i - center_idx)
            if d > radius:
                continue

            t = d / radius
            w = (1.0 - (t * t * (3.0 - 2.0 * t))) * strength
            if w <= 0.0:
                continue

            p = Vector((points[i].co[0], points[i].co[1], points[i].co[2]))
            p = p + (delta * w)
            points[i].co = (p.x, p.y, p.z)

        return True

    def sync_post(self, sync_manager, root, scene, vis_col):
        live_keys = set()
        active_id = ""

        active_obj = bpy.context.view_layer.objects.active if bpy.context and bpy.context.view_layer else None
        if active_obj and active_obj.get("af_root_name") == root.name:
            if active_obj.get("af_curve_point_handle") and active_obj.get("af_scp_id"):
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

            for i, p in enumerate(scp_prop.curve_points):
                live_keys.add((scp_prop.id, i))
                h = self._find_curve_point_handle(vis_col, root.name, scp_prop.id, i)
                if h is None:
                    h = self._create_curve_point_handle(vis_col, root, scp_prop.id, i)
                local = shape.apply_point_deformers(Vector((p.co[0], p.co[1], p.co[2])))
                h.location = proxy.matrix_world @ local

        for obj in list(vis_col.objects):
            if not obj.get("af_curve_point_handle"):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            key = (obj.get("af_scp_id"), int(obj.get("af_curve_point_index", -1)))
            if key not in live_keys:
                bpy.data.objects.remove(obj, do_unlink=True)

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph):
        if not obj.get("af_curve_point_handle"):
            return False, False, None

        scp_id = obj.get("af_scp_id")
        point_index = int(obj.get("af_curve_point_index", -1))
        scp_prop = sync_manager._get_scp_prop_by_id(root, scp_id)
        proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_id)
        if scp_prop is None or proxy is None or scp_prop.shape_type != self.shape_type:
            return True, False, None

        for i, s in enumerate(root.af_scp_system.scps):
            if s.id == scp_id:
                root.af_scp_system.active_scp_index = i
                break

        if point_index < 0 or point_index >= len(scp_prop.curve_points):
            return True, False, None

        local = proxy.matrix_world.inverted() @ obj.location
        shape = ShapeRegistry.create_from_prop(scp_prop)
        if shape is not None:
            local = shape.invert_point_deformers(local)
        did = self._apply_curve_proportional_delta(scp_prop, point_index, local)
        return True, did, scp_id if did else None
