import json
from mathutils import Vector, Quaternion
from .scp import SCP
from .attachment import Attachment
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
                raw = (scp_prop.attach_param or "").strip()
                if raw:
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            mode = parsed.get("mode")
                            if mode == "surface_frame_v1":
                                param = parsed.get("parent_param", 0.0)
                            elif mode == "mesh_anchor":
                                param = parsed.get("parent_param", 0.0)
                            else:
                                param = parsed
                        else:
                            param = parsed
                    except json.JSONDecodeError:
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
