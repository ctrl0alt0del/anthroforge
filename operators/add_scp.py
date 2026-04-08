import bpy
from mathutils import Vector

from ..core.attachment_codec import encode_surface_frame
from ..core.utils import get_af_root
from ..core.registry import SCPRegistry
from ..core.shapes.registry import ShapeRegistry
from ..core.id_utils import next_prefixed_id
from ..core.visualization.sync_runner import sync_from_scp_ids


class AF_OT_AddSCP(bpy.types.Operator):
    bl_idname = "af.add_scp"
    bl_label = "Add SCP"
    bl_description = "Add a new Structural Control Primitive"

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            self.report({"ERROR"}, "No AF_ROOT found in scene.")
            return {"CANCELLED"}

        scp_collection = root.af_scp_system.scps
        new_scp = scp_collection.add()

        new_scp.id = next_prefixed_id(scp_collection, "SCP")
        new_scp.name = new_scp.id
        new_scp.shape_type = context.scene.af_scp_type

        new_scp.local_origin = (0.0, 0.0, 0.0)
        new_scp.local_rotation = (1.0, 0.0, 0.0, 0.0)
        new_scp.local_rotation_euler = (0.0, 0.0, 0.0)
        new_scp.local_scale = (1.0, 1.0, 1.0)

        shape_cls = ShapeRegistry.get(new_scp.shape_type)
        if shape_cls:
            shape_cls.init_scp_prop_defaults(new_scp)
        ShapeRegistry.apply_creation_to_scp(new_scp.shape_type, context.scene, new_scp)

        parent_obj = context.scene.af_new_parent_obj
        parent_id = parent_obj.get("af_scp_id", "") if parent_obj else ""

        if parent_id:
            new_scp.parent_id = parent_id

            runtime = SCPRegistry(root)
            runtime.build()
            parent_scp = runtime.registry.get(parent_id)

            if parent_scp:
                params = parent_scp.shape.get_attach_params()
                first_param = params[0] if params else 0.0
            else:
                first_param = 0.0

            new_scp.attach_param = encode_surface_frame(
                parent_param=first_param,
                child_origin_local=Vector((0.0, 0.0, 0.0)),
                child_tangent_local=Vector((1.0, 0.0, 0.0)),
                child_normal_local=Vector((0.0, 0.0, 1.0)),
            )
        else:
            new_scp.parent_id = ""
            new_scp.attach_param = ""

        sync_from_scp_ids(root=root, scene=context.scene, scp_ids={new_scp.id})

        root.af_scp_system.active_scp_index = len(root.af_scp_system.scps) - 1
        new_id = new_scp.id
        proxy = None
        for obj in context.scene.objects:
            if (
                obj.get("af_proxy")
                and obj.get("af_root_name") == root.name
                and obj.get("af_scp_id") == new_id
                and not obj.get("af_mirror_proxy")
            ):
                proxy = obj
                break

        if proxy:
            for o in context.selected_objects:
                o.select_set(False)
            proxy.select_set(True)
            context.view_layer.objects.active = proxy

        self.report({"INFO"}, f"Added {new_scp.shape_type} SCP")
        return {"FINISHED"}
