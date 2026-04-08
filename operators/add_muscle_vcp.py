import bpy

from ..core.utils import get_af_root
from ..core.id_utils import next_prefixed_id
from ..core.visualization.sync_runner import sync_from_muscle_ids


def _selected_fiber_ids(context, root):
    ids = []
    seen = set()
    active_id = _active_selected_fiber_id(context, root)
    for obj in context.selected_objects:
        fid = _selected_proxy_fiber_id(obj, root.name)
        if not fid or fid in seen or fid == active_id:
            continue
        ids.append(fid)
        seen.add(fid)
    if active_id and active_id not in seen:
        ids.append(active_id)
    return ids


def _active_selected_fiber_id(context, root):
    active = context.active_object
    if (
        active
        and active.get("af_fiber_proxy")
        and active.get("af_root_name") == root.name
        and active.get("af_fiber_id")
        and active.select_get()
    ):
        return active.get("af_fiber_id")
    return None


def _selected_proxy_fiber_id(obj, root_name):
    if not obj.get("af_fiber_proxy") or obj.get("af_root_name") != root_name:
        return None
    return obj.get("af_fiber_id")


class AF_OT_AddMuscleVCP(bpy.types.Operator):
    bl_idname = "af.add_muscle_vcp"
    bl_label = "Create Muscle From Selected Fibers"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty(name="Name", default="")
    closed_v: bpy.props.BoolProperty(name="Closed Ring (V)", default=False)

    def _resolve_fibers(self, vcp, fiber_ids):
        fibers_by_id = {f.id: f for f in vcp.fibers}
        fibers = []
        for fid in fiber_ids:
            f = fibers_by_id.get(fid)
            if f is None:
                self.report({"ERROR"}, f"Fiber '{fid}' not found.")
                return None, None
            fibers.append(f)
        return fibers_by_id, fibers

    def _validate_compatible(self, fibers):
        node_count = int(fibers[0].node_count)
        anchor_count = len(fibers[0].mid_touches)
        for f in fibers[1:]:
            if int(f.node_count) != node_count:
                self.report({"ERROR"}, "Selected fibers must have identical node_count.")
                return False
            if len(f.mid_touches) != anchor_count:
                self.report({"ERROR"}, "Selected fibers must have identical anchor structure.")
                return False
        return True

    def _init_muscle(self, vcp, muscle_id):
        m = vcp.muscles.add()
        m.id = muscle_id
        m.name = self.name.strip() if self.name.strip() else muscle_id
        m.closed_v = bool(self.closed_v)
        m.inflation_enabled = True
        m.inflation_max_value = 0.05
        m.inflation_falloff_type = "GAUSSIAN"
        m.inflation_falloff_radius = 0.2
        m.inflation_ctrl_world = (0.0, 0.0, 0.0)
        return m

    def _detach_fiber_from_other_muscles(self, vcp, muscle_id, fid):
        for old_m in vcp.muscles:
            if old_m.id == muscle_id:
                continue
            rm = [idx for idx, ref in enumerate(old_m.fiber_refs) if ref.fiber_id == fid]
            for idx in reversed(rm):
                old_m.fiber_refs.remove(idx)

    def _assign_fibers_to_muscle(self, vcp, m, muscle_id, fiber_ids, fibers_by_id):
        for fid in fiber_ids:
            self._detach_fiber_from_other_muscles(vcp, muscle_id, fid)
            ref = m.fiber_refs.add()
            ref.fiber_id = fid
            fibers_by_id[fid].muscle_id = muscle_id
        m.active_fiber_ref_index = 0 if len(m.fiber_refs) > 0 else -1

    def _find_inflation_ctrl(self, context, root_name, muscle_id):
        ctrl_name = f"AF_{muscle_id}_INFL_MAX"
        for obj in context.scene.objects:
            if obj.name == ctrl_name and obj.get("af_muscle_inflation_ctrl"):
                if obj.get("af_root_name") == root_name and obj.get("af_muscle_id") == muscle_id:
                    return obj
        return None

    def _select_object(self, context, obj):
        if obj is None:
            return
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

    def _set_active_muscle(self, vcp, muscle_id):
        vcp.active_vcp_type = "MUSCLE"
        vcp.active_vcp_id = muscle_id

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({"ERROR"}, "No AF_ROOT found.")
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        fiber_ids = _selected_fiber_ids(context, root)

        if len(fiber_ids) < 2:
            self.report({"ERROR"}, "Select at least 2 fiber proxies in viewport (Shift-select).")
            return {"CANCELLED"}

        fibers_by_id, fibers = self._resolve_fibers(vcp, fiber_ids)
        if fibers is None:
            return {"CANCELLED"}
        if not self._validate_compatible(fibers):
            return {"CANCELLED"}

        muscle_id = next_prefixed_id(vcp.muscles, "MUSCLE")
        m = self._init_muscle(vcp, muscle_id)
        self._assign_fibers_to_muscle(vcp, m, muscle_id, fiber_ids, fibers_by_id)
        self._set_active_muscle(vcp, muscle_id)
        sync_from_muscle_ids(root=root, scene=context.scene, muscle_ids={muscle_id})
        self._select_object(context, self._find_inflation_ctrl(context, root.name, muscle_id))
        self.report({"INFO"}, f"Created {muscle_id} from {len(fiber_ids)} fibers")
        return {"FINISHED"}
