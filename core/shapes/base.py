from abc import ABC, abstractmethod
from mathutils import Vector, Matrix


class ShapeStrategy(ABC):
    """
    Base interface for all SCP shapes.
    All shapes operate in local SCP space.
    """

    @abstractmethod
    def get_attach_params(self):
        """
        Returns a list of parametric coordinates.
        These are NOT world positions.
        """
        pass

    @abstractmethod
    def compute_local_point(self, param):
        """
        Given a param, returns local-space position (Vector).
        """
        pass

    def compute_world_point(self, param, scp_matrix: Matrix):
        """
        Converts param to world position using SCP transform matrix.
        """
        local = self.compute_local_point(param)
        return scp_matrix @ local

    @abstractmethod
    def render_debug(self, scp_matrix: Matrix):
        """
        Debug draw representation.
        Does NOT store state.
        """
        pass
