import json
import bpy

from ..core.utils import get_af_root
from ..core.attachment import Attachment
from ..core.registry import SCPRegistry
from ..core.visualization.fiber_sync import register_fiber_sync
from ..core.visualization.muscle_sync import register_muscle_sync


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

        runtime = SCPRegistry(root)
        runtime.build()

        def first_param_for(parent_id):
            parent = runtime.registry.get(parent_id)
            if not parent:
                return 0.0
            params = parent.shape.get_attach_params()
            return params[0] if params else 0.0

        a_param = first_param_for(origin_id)
        b_param = first_param_for(insertion_id)

        fibers = root.af_vcp_system.fibers
        f = fibers.add()
        f.id = f"FIBER_{len(fibers)}"

        origin = Attachment(parent_id=origin_id, param=a_param)
        insertion = Attachment(parent_id=insertion_id, param=b_param)

        f.a_parent_id = origin.parent_id
        f.a_attach_param = json.dumps(origin.param)

        f.b_parent_id = insertion.parent_id
        f.b_attach_param = json.dumps(insertion.param)

        # Solver defaults (current model)
        f.node_count = 64
        f.iterations_interactive = 12
        f.iterations_bake = 180
        f.stretch_stiffness = 0.9  # used as shorten strength in current solver
        f.bend_stiffness = 0.02
        f.collision_margin = 0.002
        f.damping = 0.01
        f.not_converged = False

        # Visual
        f.thickness = 0.01

        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        register_muscle_sync().sync_root_to_scene(root=root, scene=context.scene)

        self.report({'INFO'}, f"Added {f.id}")
        return {'FINISHED'}
