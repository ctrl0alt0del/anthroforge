from mathutils import Vector, Quaternion
from .scp import SCP
from .attachment import Attachment
from .attachment_codec import parse_scp_attach_param
from .shapes.registry import ShapeRegistry


class SCPRegistry:
    def __init__(self, root_object):
        self.root = root_object
        self.registry = {}

    def _attachment_from_prop(self, scp_prop):
        if not scp_prop.parent_id:
            return None
        mode, payload = parse_scp_attach_param(scp_prop.attach_param)
        parent_param = payload.get("parent_param", 0.0) if mode == "surface_frame_v1" else 0.0
        return Attachment(scp_prop.parent_id, parent_param)

    def _build_scp_instance(self, scp_prop, shape):
        return SCP(
            scp_id=scp_prop.id,
            shape=shape,
            local_origin=Vector(scp_prop.local_origin),
            local_rotation=Quaternion(scp_prop.local_rotation).to_matrix(),
            local_scale=Vector(scp_prop.local_scale),
            attachment=self._attachment_from_prop(scp_prop),
        )

    def _link_parent_children(self):
        for scp in self.registry.values():
            if not scp.attachment:
                continue
            parent = self.registry.get(scp.attachment.parent_id)
            if parent:
                parent.add_child(scp)

    def build(self):
        self.registry.clear()
        for scp_prop in self.root.af_scp_system.scps:
            shape = ShapeRegistry.create_from_prop(scp_prop)
            if shape is None:
                continue
            scp = self._build_scp_instance(scp_prop, shape)
            self.registry[scp.id] = scp
        self._link_parent_children()
