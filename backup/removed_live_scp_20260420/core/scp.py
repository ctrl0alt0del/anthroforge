from mathutils import Matrix, Vector
from .attachment import Attachment

class SCP:

    def __init__(self, scp_id: str, shape, 
                 local_origin=Vector((0, 0, 0)),
                 local_rotation=Matrix.Identity(3),
                 local_scale=Vector((1, 1, 1)),
                 attachment: Attachment = None):

        self.id = scp_id
        self.shape = shape
        self.attachment = attachment

        self.local_origin = local_origin
        self.local_rotation = local_rotation
        self.local_scale = local_scale

        self.children = []

    # ------------------------------
    # Hierarchy Management
    # ------------------------------

    def add_child(self, child_scp):
        self.children.append(child_scp)

    # ------------------------------
    # Local Transform
    # ------------------------------

    def get_local_matrix(self):
        T = Matrix.Translation(self.local_origin)
        R = self.local_rotation.to_4x4()
        S = Matrix.Diagonal((*self.local_scale, 1.0))
        return T @ R @ S

    # ------------------------------
    # World Matrix Resolution
    # ------------------------------

    def get_world_matrix(self, registry):
        """
        registry: dict of all SCPs by id
        """

        if self.attachment is None:
            # root-level SCP
            return self.get_local_matrix()

        parent = registry[self.attachment.parent_id]

        parent_world = parent.get_world_matrix(registry)

        # resolve attachment point in parent local space
        parent_shape = parent.shape
        attach_local = parent_shape.compute_local_point(self.attachment.param)

        attach_world = parent_world @ attach_local

        # build this SCP transform at attachment point
        T = Matrix.Translation(attach_world)
        R = self.local_rotation.to_4x4()
        S = Matrix.Diagonal((*self.local_scale, 1.0))

        return T @ R @ S

