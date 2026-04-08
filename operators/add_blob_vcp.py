import bpy

from ..core.id_utils import next_prefixed_id
from ..core.utils import get_af_root
from ..core.visualization.sync_runner import sync_from_blob_ids


def _init_blob_defaults(blob, scene):
    blob.center_world = scene.cursor.location
    blob.radius = 0.2
    blob.shape = "SPHERE"
    blob.axis_scale = (1.0, 1.0, 1.0)
    blob.resolution = 24
    blob.control_point_world = scene.cursor.location
    blob.gravity_dir = (0.0, 0.0, -1.0)
    blob.sag_strength = 0.35
    blob.sag_limit = 0.35
    blob.stiffness = 0.25
    blob.iterations = 20


def _set_blob_target(blob, target):
    if not target:
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "NONE", "", ""
        return
    if target.get("af_muscle_proxy") and target.get("af_muscle_id"):
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "MUSCLE", target.get("af_muscle_id"), ""
        return
    if target.get("af_proxy") and target.get("af_scp_id"):
        blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "SCP", target.get("af_scp_id"), ""
        return
    blob.attach_target_type, blob.attach_target_id, blob.attach_target_object_name = "OBJECT", "", target.name


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
        blob_id = next_prefixed_id(blobs, "BLOB")
        b = blobs.add()
        b.id = blob_id
        b.name = blob_id
        _init_blob_defaults(b, context.scene)
        _set_blob_target(b, context.scene.af_new_blob_target_obj or context.active_object)

        vcp.active_vcp_type = "BLOB"
        vcp.active_vcp_id = b.id

        sync_from_blob_ids(root=root, scene=context.scene, blob_ids={b.id})

        self.report({"INFO"}, f"Added {b.id}")
        return {"FINISHED"}
