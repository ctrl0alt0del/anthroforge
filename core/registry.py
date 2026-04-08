from mathutils import Vector, Quaternion
from .scp import SCP
from .attachment import Attachment
from .attachment_codec import parse_scp_attach_param
from .shapes.registry import ShapeRegistry


class SCPRegistry:
    def __init__(self, root_object):
        self.root = root_object
        self.registry = {}

    def build(self):
        self.registry.clear()

        for scp_prop in self.root.af_scp_system.scps:
            shape = ShapeRegistry.create_from_prop(scp_prop)
            if not shape:
                continue

            origin = Vector(scp_prop.local_origin)
            rotation = Quaternion(scp_prop.local_rotation).to_matrix()
            scale = Vector(scp_prop.local_scale)

            attachment = None
            if scp_prop.parent_id:
                mode, payload = parse_scp_attach_param(scp_prop.attach_param)
                if mode == "surface_frame_v1":
                    param = payload.get("parent_param", 0.0)
                elif mode == "mesh_anchor":
                    param = 0.0
                else:
                    param = 0.0
                attachment = Attachment(scp_prop.parent_id, param)

            scp = SCP(
                scp_id=scp_prop.id,
                shape=shape,
                local_origin=origin,
                local_rotation=rotation,
                local_scale=scale,
                attachment=attachment,
            )

            self.registry[scp.id] = scp

        for scp in self.registry.values():
            if scp.attachment:
                parent = self.registry.get(scp.attachment.parent_id)
                if parent:
                    parent.add_child(scp)
