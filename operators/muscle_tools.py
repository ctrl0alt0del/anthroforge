import bpy
from ..core.utils import get_af_root
from ..core.visualization.muscle_sync import register_muscle_sync


class AF_OT_FlipMuscleNormals(bpy.types.Operator):
    bl_idname = "af.flip_muscle_normals"
    bl_label = "Flip Muscle Normals"
    bl_options = {"REGISTER", "UNDO"}

    muscle_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        mid = self.muscle_id or vcp.active_vcp_id
        m = next((x for x in vcp.muscles if x.id == mid), None)
        if m is None:
            self.report({"ERROR"}, "Muscle not found.")
            return {"CANCELLED"}

        m.flip_normals = not m.flip_normals
        register_muscle_sync().sync_root_to_scene(root=root, scene=context.scene)
        return {"FINISHED"}
