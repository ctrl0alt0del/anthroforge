import bpy

from ..core.utils import get_af_root
from ..core.visualization.sync_runner import sync_from_blob_ids


class AF_OT_AddBlobVCP(bpy.types.Operator):
    bl_idname = "af.add_blob_vcp"
    bl_label = "Add Blob VCP"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({"ERROR"}, "No AF_ROOT found.")
            return {"CANCELLED"}

        vcp = root.af_vcp_system
        blobs = vcp.blobs

        i = 1
        existing = {b.id for b in blobs}
        blob_id = f"BLOB_{i}"
        while blob_id in existing:
            i += 1
            blob_id = f"BLOB_{i}"

        b = blobs.add()
        b.id = blob_id
        b.name = blob_id

        b.center_world = context.scene.cursor.location
        b.radius = 0.2
        b.shape = "SPHERE"
        b.axis_scale = (1.0, 1.0, 1.0)
        b.resolution = 24
        b.control_point_world = context.scene.cursor.location

        b.gravity_dir = (0.0, 0.0, -1.0)
        b.sag_strength = 0.35
        b.sag_limit = 0.35

        b.stiffness = 0.25
        b.iterations = 20

        target = context.scene.af_new_blob_target_obj or context.active_object
        if target:
            if target.get("af_muscle_proxy") and target.get("af_muscle_id"):
                b.attach_target_type = "MUSCLE"
                b.attach_target_id = target.get("af_muscle_id")
                b.attach_target_object_name = ""
            elif target.get("af_proxy") and target.get("af_scp_id"):
                b.attach_target_type = "SCP"
                b.attach_target_id = target.get("af_scp_id")
                b.attach_target_object_name = ""
            else:
                b.attach_target_type = "OBJECT"
                b.attach_target_id = ""
                b.attach_target_object_name = target.name
        else:
            b.attach_target_type = "NONE"
            b.attach_target_id = ""
            b.attach_target_object_name = ""

        vcp.active_vcp_type = "BLOB"
        vcp.active_vcp_id = b.id

        sync_from_blob_ids(root=root, scene=context.scene, blob_ids={b.id})

        self.report({"INFO"}, f"Added {b.id}")
        return {"FINISHED"}
