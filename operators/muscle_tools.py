import bpy

from ..core.utils import get_af_root
from ..core.visualization.sync_runner import sync_from_muscle_ids


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
        sync_from_muscle_ids(root=root, scene=context.scene, muscle_ids={m.id})
        return {"FINISHED"}


class AF_OT_SelectMuscleInflationCtrl(bpy.types.Operator):
    bl_idname = "af.select_muscle_inflation_ctrl"
    bl_label = "Select Max Inflation Point"
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

        # Ensure control exists
        sync_from_muscle_ids(root=root, scene=context.scene, muscle_ids={m.id})

        ctrl = None
        for obj in context.scene.objects:
            if (
                obj.get("af_muscle_inflation_ctrl")
                and obj.get("af_root_name") == root.name
                and obj.get("af_muscle_id") == m.id
            ):
                ctrl = obj
                break

        if ctrl is None:
            self.report({"ERROR"}, "Inflation control not found.")
            return {"CANCELLED"}

        for o in context.selected_objects:
            o.select_set(False)
        ctrl.select_set(True)
        context.view_layer.objects.active = ctrl

        vcp.active_vcp_type = "MUSCLE"
        vcp.active_vcp_id = m.id

        return {"FINISHED"}
