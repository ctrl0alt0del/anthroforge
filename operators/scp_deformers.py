import bpy

from ..core.utils import get_af_root
from ..core.shapes.state_codec import set_deformer_param_patch


def _find_scp(root, scp_id):
    sid = str(scp_id or "")
    if root is None or not sid:
        return None
    for scp in root.af_scp_system.scps:
        if str(getattr(scp, "id", "") or "") == sid:
            return scp
    return None


def _set_deformer_enabled(scp, deformer_id, enabled):
    did = str(deformer_id or "")
    on = bool(enabled)
    if did == "parallelepiped_bend":
        if not hasattr(scp, "parallelepiped_bend_enabled"):
            return False
        scp.parallelepiped_bend_enabled = on
        set_deformer_param_patch(scp, did, "enabled", on)
        return True
    if did == "ellipsoid_clip":
        if not hasattr(scp, "ellipsoid_clip_enabled"):
            return False
        scp.ellipsoid_clip_enabled = on
        set_deformer_param_patch(scp, did, "enabled", on)
        if on:
            c1 = bool(getattr(scp, "ellipsoid_clip1_enabled", False))
            c2 = bool(getattr(scp, "ellipsoid_clip2_enabled", False))
            if not c1 and not c2:
                scp.ellipsoid_clip1_enabled = True
                set_deformer_param_patch(scp, did, "clip1_enabled", True)
        else:
            if hasattr(scp, "ellipsoid_clip1_enabled"):
                scp.ellipsoid_clip1_enabled = False
                set_deformer_param_patch(scp, did, "clip1_enabled", False)
            if hasattr(scp, "ellipsoid_clip2_enabled"):
                scp.ellipsoid_clip2_enabled = False
                set_deformer_param_patch(scp, did, "clip2_enabled", False)
        return True
    return False


class AF_OT_AddSCPDeformer(bpy.types.Operator):
    bl_idname = "af.add_scp_deformer"
    bl_label = "Add Deformer"
    bl_options = {"REGISTER", "UNDO"}

    scp_id: bpy.props.StringProperty(name="SCP ID", default="")
    deformer_id: bpy.props.StringProperty(name="Deformer ID", default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        scp = _find_scp(root, self.scp_id)
        if scp is None:
            self.report({"ERROR"}, "SCP not found")
            return {"CANCELLED"}
        if not _set_deformer_enabled(scp, self.deformer_id, True):
            self.report({"ERROR"}, f"Unsupported deformer: {self.deformer_id}")
            return {"CANCELLED"}
        return {"FINISHED"}


class AF_OT_RemoveSCPDeformer(bpy.types.Operator):
    bl_idname = "af.remove_scp_deformer"
    bl_label = "Remove Deformer"
    bl_options = {"REGISTER", "UNDO"}

    scp_id: bpy.props.StringProperty(name="SCP ID", default="")
    deformer_id: bpy.props.StringProperty(name="Deformer ID", default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        scp = _find_scp(root, self.scp_id)
        if scp is None:
            self.report({"ERROR"}, "SCP not found")
            return {"CANCELLED"}
        if not _set_deformer_enabled(scp, self.deformer_id, False):
            self.report({"ERROR"}, f"Unsupported deformer: {self.deformer_id}")
            return {"CANCELLED"}
        return {"FINISHED"}
