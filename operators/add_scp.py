import bpy
from ..core.utils import get_af_root
from ..core.visualization.sync import register_sync
from ..core.shapes.registry import ShapeRegistry

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

        new_scp.id = f"SCP_{len(scp_collection)}"
        new_scp.shape_type = context.scene.af_scp_type
        shape_cls = ShapeRegistry.get(new_scp.shape_type)
        if shape_cls:
            shape_cls.init_scp_prop_defaults(new_scp)
        ShapeRegistry.apply_creation_to_scp(new_scp.shape_type, context.scene, new_scp)

        # Default transform
        new_scp.local_origin = (0.0, 0.0, 0.0)
        new_scp.local_rotation = (1.0, 0.0, 0.0, 0.0)  # quaternion identity
        new_scp.local_rotation_euler = (0.0, 0.0, 0.0)
        new_scp.local_scale = (1.0, 1.0, 1.0)

        new_scp.parent_id = ""
        new_scp.attach_param = ""

        self.report({'INFO'}, f"Added {new_scp.shape_type} SCP")
        register_sync().sync_root_to_scene(root=root, scene=context.scene)

        return {'FINISHED'}
