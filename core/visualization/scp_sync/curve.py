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

    def _point_vec(self, p):
        return Vector((p.co[0], p.co[1], p.co[2]))

    def _proportional_weight(self, d, radius, strength):
        if d > radius:
            return 0.0
        t = d / radius
        return (1.0 - (t * t * (3.0 - 2.0 * t))) * strength

    def _apply_weighted_delta(self, points, center_idx, delta, radius, strength):
        for i in range(len(points)):
            if i == center_idx:
                continue
            w = self._proportional_weight(abs(i - center_idx), radius, strength)
            if w <= 0.0:
                continue
            p = self._point_vec(points[i]) + (delta * w)
            points[i].co = (p.x, p.y, p.z)

    def _apply_curve_proportional_delta(self, scp_prop, center_idx, center_new_local):
        points = scp_prop.curve_points
        n = len(points)
        if not (0 <= center_idx < n):
            return False

        old_center = self._point_vec(points[center_idx])
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
        self._apply_weighted_delta(points, center_idx, delta, radius, strength)
        return True

    def _active_scp_id(self, root):
        active_obj = bpy.context.view_layer.objects.active if bpy.context and bpy.context.view_layer else None
        if active_obj and active_obj.get("af_root_name") == root.name:
            if active_obj.get("af_curve_point_handle") and active_obj.get("af_scp_id"):
                return active_obj.get("af_scp_id")
            if active_obj.get("af_proxy") and active_obj.get("af_scp_id"):
                return active_obj.get("af_scp_id")
        idx = root.af_scp_system.active_scp_index
        if 0 <= idx < len(root.af_scp_system.scps):
            return root.af_scp_system.scps[idx].id
        return ""

    def _sync_curve_handles(self, sync_manager, root, scene, vis_col, scp_prop, live_keys):
        proxy = sync_manager._find_proxy_in_scene(scene, root.name, scp_prop.id)
        shape = ShapeRegistry.create_from_prop(scp_prop) if proxy is not None else None
        if proxy is None or shape is None:
            return
        for i, p in enumerate(scp_prop.curve_points):
            live_keys.add((scp_prop.id, i))
            h = self._find_curve_point_handle(vis_col, root.name, scp_prop.id, i)
            if h is None:
                h = self._create_curve_point_handle(vis_col, root, scp_prop.id, i)
            h.location = proxy.matrix_world @ shape.apply_point_deformers(self._point_vec(p))

    def _cleanup_stale_handles(self, vis_col, root_name, live_keys):
        for obj in list(vis_col.objects):
            if not obj.get("af_curve_point_handle"):
                continue
            if obj.get("af_root_name") != root_name:
                continue
            key = (obj.get("af_scp_id"), int(obj.get("af_curve_point_index", -1)))
            if key not in live_keys:
                bpy.data.objects.remove(obj, do_unlink=True)

    def sync_post(self, sync_manager, root, scene, vis_col):
        live_keys = set()
        active_id = self._active_scp_id(root)

        for scp_prop in root.af_scp_system.scps:
            if scp_prop.id == active_id and scp_prop.shape_type == self.shape_type:
                self._sync_curve_handles(sync_manager, root, scene, vis_col, scp_prop, live_keys)
        self._cleanup_stale_handles(vis_col, root.name, live_keys)

    def handle_object_update(self, sync_manager, root, scene, vis_col, obj, depsgraph, control_binding=None):
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

        local_deformed = proxy.matrix_world.inverted() @ obj.location
        shape = ShapeRegistry.create_from_prop(scp_prop)
        if shape is not None:
            space = str(getattr(control_binding, "space", "FINAL") or "FINAL")
            local = shape.invert_point_from_space(local_deformed, space=space)
        else:
            local = local_deformed
        did = self._apply_curve_proportional_delta(scp_prop, point_index, local)
        return True, did, scp_id if did else None
