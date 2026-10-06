"""Own SCP triangle snapshots on Blender's main thread for native validation."""
from dataclasses import dataclass
import numpy as np
from ..muscle_pairs.model import immutable


@dataclass(frozen=True)
class Obstacle:
    vertices: object
    faces: object


def capture(scene, root):
    from ..scp_runtime.common import iter_geometry_mesh_scp_objects
    values = []; depsgraph = scene.view_layers[0].depsgraph
    for obj in iter_geometry_mesh_scp_objects(scene, root.name):
        evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles(); points = np.empty((len(mesh.vertices), 3))
            mesh.vertices.foreach_get('co', points.ravel()); matrix = np.asarray(evaluated.matrix_world, dtype=float)
            faces = np.array([t.vertices[:] for t in mesh.loop_triangles], dtype=np.int64).reshape(-1, 3)
            if len(faces): values.append(Obstacle(immutable(points @ matrix[:3, :3].T+matrix[:3, 3], float, (None, 3)), immutable(faces, 'int64', (None, 3))))
        finally: evaluated.to_mesh_clear()
    return tuple(values)
