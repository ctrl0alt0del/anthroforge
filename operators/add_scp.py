import json
import bpy

from ..core.utils import get_af_root
from ..core.registry import SCPRegistry
from ..core.shapes.registry import ShapeRegistry
from ..core.visualization.sync import register_sync


class AF_OT_AddSCP(bpy.types.Operator):
    bl_idname = "af.add_scp"
    bl_label = "Add SCP"
    bl_description = "Add a new Structural Control Primitive"

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({'ERROR'}, "No AF_ROOT found in scene.")
            return {'CANCELLED'}

        scp_collection = root.af_system.scps
        new_scp = scp_collection.add()

        # Identity / shape
        new_scp.id = f"SCP_{len(scp_collection)}"
        new_scp.shape_type = context.scene.af_scp_type

        # Transform defaults
        new_scp.local_origin = (0.0, 0.0, 0.0)
        new_scp.local_rotation = (1.0, 0.0, 0.0, 0.0)   # quaternion identity
        new_scp.local_rotation_euler = (0.0, 0.0, 0.0)  # UI euler
        new_scp.local_scale = (1.0, 1.0, 1.0)

        # Shape defaults + apply create-form params
        shape_cls = ShapeRegistry.get(new_scp.shape_type)
        if shape_cls:
            shape_cls.init_scp_prop_defaults(new_scp)
        ShapeRegistry.apply_creation_to_scp(new_scp.shape_type, context.scene, new_scp)

        # Parent from single reference field (SCP proxy object)
        parent_obj = context.scene.af_new_parent_obj
        parent_id = parent_obj.get("af_scp_id", "") if parent_obj else ""

        if parent_id:
            new_scp.parent_id = parent_id
            new_scp.attach_param = "0.0"
            # Starter default attach param: first parent attach param if available
            runtime = SCPRegistry(root)
            runtime.build()
            parent_scp = runtime.registry.get(parent_id)

            default_param = 0.0
            if parent_scp:
                params = parent_scp.shape.get_attach_params()
                if params:
                    default_param = params[0]

            new_scp.attach_param = json.dumps(default_param)
        else:
            new_scp.parent_id = ""
            new_scp.attach_param = ""

        # Sync scene proxies
        register_sync().sync_root_to_scene(root=root, scene=context.scene)

        self.report({'INFO'}, f"Added {new_scp.shape_type} SCP")
        return {'FINISHED'}
