from abc import ABC, abstractmethod
from mathutils import Matrix, Vector
from .deformers import normalize_deformer_sequence


class ShapeStrategy(ABC):
    type_id = "BASE"
    label = "Base"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    supports_fiber_collision = True

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls()

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        pass

    # Scene "new SCP" form lifecycle
    @classmethod
    def register_scene_props(cls):
        pass

    @classmethod
    def unregister_scene_props(cls):
        pass

    # UI hooks
    @classmethod
    def draw_creation_ui(cls, layout, scene):
        pass

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        pass

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        pass

    @abstractmethod
    def get_attach_params(self):
        pass

    @abstractmethod
    def compute_local_point(self, param):
        pass

    def sample_attachment_frame_local(self, param):
        """
        Returns (origin, tangent, normal) in local space.
        Subclasses should override for higher-quality frames.
        """
        origin = self.compute_local_point(param)
        normal = origin.copy()
        if normal.length <= 1e-8:
            normal = Vector((0.0, 0.0, 1.0))
        else:
            normal.normalize()

        tangent = normal.cross(Vector((0.0, 0.0, 1.0)))
        if tangent.length <= 1e-8:
            tangent = normal.cross(Vector((0.0, 1.0, 0.0)))
        if tangent.length <= 1e-8:
            tangent = Vector((1.0, 0.0, 0.0))
        else:
            tangent.normalize()
        return origin, tangent, normal

    def compute_world_point(self, param, scp_matrix: Matrix):
        return scp_matrix @ self.compute_local_point(param)

    # Deformation pipeline (optional per-shape)
    def get_deformers(self):
        return []

    def apply_point_deformers(self, local_point):
        p = local_point.copy()
        for d in normalize_deformer_sequence(self.get_deformers()):
            p = d.forward(p, self)
        return p

    def invert_point_deformers(self, deformed_local_point):
        p = deformed_local_point.copy()
        deformers = list(normalize_deformer_sequence(self.get_deformers()))
        for d in reversed(deformers):
            p = d.inverse(p, self)
        return p

    # Optional hook for mirrored control-point propagation.
    # Return tuple(pair_index, pair_local_base_point) or None.
    def mirror_pair_update_from_handle(self, proxy_obj, handle_world_location, vert_index, scp_prop):
        for d in normalize_deformer_sequence(self.get_deformers()):
            req = d.request_handle_update(
                shape=self,
                proxy_obj=proxy_obj,
                handle_world_location=handle_world_location,
                vert_index=vert_index,
                scp_prop=scp_prop,
            )
            if req is None:
                continue
            applied = self.apply_deformer_update_request(req)
            if applied is not None:
                return applied
        return None

    def apply_deformer_update_request(self, request):
        rtype = str(getattr(request, "request_type", "") or "")
        payload = dict(getattr(request, "payload", {}) or {})
        if rtype == "MIRROR_PAIR_POINT":
            pair_index = int(payload.get("pair_index", -1))
            pair_local = payload.get("pair_local_base_point", None)
            if pair_local is None:
                return None
            return pair_index, pair_local
        return None

    @abstractmethod
    def ensure_proxy_object(self, obj):
        pass
