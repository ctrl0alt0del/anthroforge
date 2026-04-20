from abc import ABC, abstractmethod
from mathutils import Matrix, Vector
from .deformers import normalize_deformer_sequence
from .pipeline import DeformerPipeline
from .state import DeformerState, ShapeState
from .state_codec import get_deformer_param_overrides


class ShapeStrategy(ABC):
    type_id = "BASE"
    label = "Base"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    supports_fiber_collision = True

    def _ensure_deformer_state_runtime(self):
        if not hasattr(self, "_deformer_param_overrides"):
            self._deformer_param_overrides = {}
        if not hasattr(self, "_shape_state_version"):
            self._shape_state_version = 0
        if not hasattr(self, "_mirror_source_enabled"):
            self._mirror_source_enabled = False
        if not hasattr(self, "_mirror_axis"):
            self._mirror_axis = "X"

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls()

    @classmethod
    def hydrate_from_scp_prop(cls, shape, scp_prop):
        try:
            shape._deformer_param_overrides = get_deformer_param_overrides(scp_prop)
        except Exception:
            shape._deformer_param_overrides = {}
        shape._mirror_source_enabled = bool(getattr(scp_prop, "mirror_enabled", False))
        shape._mirror_axis = str(getattr(scp_prop, "mirror_axis", "X") or "X")
        return shape

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

    # Representative base-space points used to build stage runtime context.
    # Should reflect geometry/control domain for stack-dependent deformers.
    def deformer_domain_points(self):
        return []

    # Non-geometry stack behaviors used by controls/runtime metadata.
    def get_control_behaviors(self):
        return []

    def _deformer_state_for(self, deformer):
        self._ensure_deformer_state_runtime()
        did = str(getattr(deformer, "deformer_id", deformer.__class__.__name__.lower()) or "")
        priority = int(getattr(deformer, "priority", 100))
        params = dict(deformer.extract_params(self) or {})
        override = self._deformer_param_overrides.get(did, None)
        if isinstance(override, dict):
            params.update(dict(override))
        return DeformerState(
            deformer_id=did,
            enabled=bool(params.pop("enabled", True)),
            order=int(params.pop("order", priority)),
            params=params,
            version=int(self._shape_state_version),
        )

    def build_shape_state(self):
        self._ensure_deformer_state_runtime()
        deformers = [self._deformer_state_for(d) for d in normalize_deformer_sequence(self.get_deformers())]
        return ShapeState(
            shape_type=str(getattr(self, "type_id", "BASE")),
            base_data={
                "mirror_source_enabled": bool(getattr(self, "_mirror_source_enabled", False)),
                "mirror_axis": str(getattr(self, "_mirror_axis", "X") or "X"),
            },
            deformers=deformers,
            version=int(self._shape_state_version),
        )

    def get_deformer_state(self, deformer_id):
        did = str(deformer_id or "")
        if not did:
            return None
        for ds in self.build_shape_state().deformers:
            if str(getattr(ds, "deformer_id", "") or "") == did:
                return ds
        return None

    def is_mirror_source(self):
        self._ensure_deformer_state_runtime()
        return bool(getattr(self, "_mirror_source_enabled", False))

    def mirror_axis(self):
        self._ensure_deformer_state_runtime()
        return str(getattr(self, "_mirror_axis", "X") or "X")

    def set_deformer_param(self, deformer_id, key, value):
        self._ensure_deformer_state_runtime()
        did = str(deformer_id or "")
        if not did:
            return False
        bucket = self._deformer_param_overrides.setdefault(did, {})
        if bucket.get(str(key)) == value:
            return False
        bucket[str(key)] = value
        self._shape_state_version += 1
        return True

    def apply_point_deformers(self, local_point):
        pipeline = DeformerPipeline(self, self.build_shape_state())
        return pipeline.forward_point(local_point.copy())

    def invert_point_deformers(self, deformed_local_point):
        pipeline = DeformerPipeline(self, self.build_shape_state())
        return pipeline.inverse_point(deformed_local_point.copy())

    def sample_point_in_space(self, local_point, space="FINAL"):
        pipeline = DeformerPipeline(self, self.build_shape_state())
        return pipeline.sample_point_in_space(local_point.copy(), space=space)

    def invert_point_from_space(self, point_in_space, space="FINAL"):
        pipeline = DeformerPipeline(self, self.build_shape_state())
        return pipeline.inverse_point_from_space(point_in_space.copy(), space=space)

    def apply_geometry_deformers(self, verts, faces):
        pipeline = DeformerPipeline(self, self.build_shape_state())
        return pipeline.forward_geometry(verts, faces)

    # Optional hook for mirrored control-point propagation.
    # Return tuple(pair_index, pair_local_base_point) or None.
    def mirror_pair_update_from_handle(self, proxy_obj, handle_world_location, vert_index, scp_prop):
        for d in normalize_deformer_sequence(self.get_control_behaviors()):
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
