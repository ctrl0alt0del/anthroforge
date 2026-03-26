import bpy

from ..core.utils import get_af_root


class AF_OT_AddSCPConstraint(bpy.types.Operator):
    bl_idname = "af.add_scp_constraint"
    bl_label = "Add SCP Constraint"

    scp_id: bpy.props.StringProperty(default="")

    def _resolve_target_scp(self, root, context):
        if self.scp_id:
            for s in root.af_scp_system.scps:
                if s.id == self.scp_id:
                    return s
        obj = context.active_object
        if obj and obj.get("af_scp_id"):
            sid = str(obj.get("af_scp_id"))
            for s in root.af_scp_system.scps:
                if s.id == sid:
                    return s
        idx = root.af_scp_system.active_scp_index
        if 0 <= idx < len(root.af_scp_system.scps):
            return root.af_scp_system.scps[idx]
        return None

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        scp = self._resolve_target_scp(root, context)
        if scp is None:
            return {"CANCELLED"}

        c = scp.constraints.add()
        c.enabled = True
        c.priority = 100
        c.source_scp_id = ""
        c.source_prop = "PAR_SIZE_X"
        c.dest_prop = "PAR_BEND_RADIUS"
        c.calculator_type = "LINEAR"
        c.arc_source_width_prop = "PAR_SIZE_X"
        c.arc_dest_angle_prop = "PAR_BEND_ANGLE"
        c.linear_a = 1.0
        c.linear_b = 0.0
        c.in_min = 0.0
        c.in_max = 1.0
        c.out_min = 0.0
        c.out_max = 1.0
        c.clamp = True
        c.arc_full_angle = 360.0
        c.arc_width_scale = 1.0
        c.arc_width_offset = 0.0
        c.delta_initialized = False
        c.delta_src_base = 0.0
        c.delta_dst_base = 0.0
        c.delta_dst_base_2 = 0.0
        c.runtime_status = "OK"
        c.runtime_message = ""

        scp.active_constraint_index = len(scp.constraints) - 1
        return {"FINISHED"}


class AF_OT_RemoveSCPConstraint(bpy.types.Operator):
    bl_idname = "af.remove_scp_constraint"
    bl_label = "Remove SCP Constraint"

    index: bpy.props.IntProperty(default=-1)
    scp_id: bpy.props.StringProperty(default="")

    def _resolve_target_scp(self, root, context):
        if self.scp_id:
            for s in root.af_scp_system.scps:
                if s.id == self.scp_id:
                    return s
        obj = context.active_object
        if obj and obj.get("af_scp_id"):
            sid = str(obj.get("af_scp_id"))
            for s in root.af_scp_system.scps:
                if s.id == sid:
                    return s
        idx = root.af_scp_system.active_scp_index
        if 0 <= idx < len(root.af_scp_system.scps):
            return root.af_scp_system.scps[idx]
        return None

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        scp = self._resolve_target_scp(root, context)
        if scp is None:
            return {"CANCELLED"}
        i = int(self.index)
        if i < 0:
            i = scp.active_constraint_index
        if i < 0 or i >= len(scp.constraints):
            return {"CANCELLED"}

        scp.constraints.remove(i)
        scp.active_constraint_index = max(0, min(scp.active_constraint_index, len(scp.constraints) - 1))
        return {"FINISHED"}
