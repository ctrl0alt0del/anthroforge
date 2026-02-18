from abc import ABC, abstractmethod
from mathutils import Matrix


class ShapeStrategy(ABC):
    type_id = "BASE"
    label = "Base"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"

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

    def compute_world_point(self, param, scp_matrix: Matrix):
        return scp_matrix @ self.compute_local_point(param)

    @abstractmethod
    def ensure_proxy_object(self, obj):
        pass
