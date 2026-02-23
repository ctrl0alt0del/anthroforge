import json
import bpy
from ..core.utils import get_af_root
from ..core.attachment import Attachment


class AF_OT_AddFiberVCP(bpy.types.Operator):
    bl_idname = "af.add_fiber_vcp"
    bl_label = "Add Fiber VCP"

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({'ERROR'}, "No AF_ROOT found.")
            return {'CANCELLED'}

        origin_obj = context.scene.af_new_fiber_origin_obj
        insertion_obj = context.scene.af_new_fiber_insertion_obj

        if not origin_obj or not insertion_obj:
            self.report({'ERROR'}, "Select both Origin and Insertion SCPs.")
            return {'CANCELLED'}

        origin_id = origin_obj.get("af_scp_id", "")
        insertion_id = insertion_obj.get("af_scp_id", "")
        if not origin_id or not insertion_id:
            self.report({'ERROR'}, "Origin/Insertion must be SCP proxy objects.")
            return {'CANCELLED'}

        fibers = root.af_vcp_system.fibers
        f = fibers.add()
        f.id = f"FIBER_{len(fibers)}"

        origin = Attachment(parent_id=origin_id, param=0.0)
        insertion = Attachment(parent_id=insertion_id, param=0.0)

        f.a_parent_id = origin.parent_id
        f.a_attach_param = json.dumps(origin.param)

        f.b_parent_id = insertion.parent_id
        f.b_attach_param = json.dumps(insertion.param)

        f.resolution = 16
        f.thickness = 0.01

        self.report({'INFO'}, f"Added {f.id}")
        return {'FINISHED'}
