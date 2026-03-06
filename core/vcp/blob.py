from dataclasses import dataclass
from mathutils import Vector


@dataclass
class BlobVCPRuntime:
    id: str
    name: str

    center_world: Vector
    radius: float
    shape: str
    axis_scale: Vector
    resolution: int

    gravity_dir: Vector
    sag_strength: float
    sag_limit: float

    attach_target_type: str
    attach_target_id: str
    attach_target_object_name: str

    control_point_world: Vector

    stiffness: float
    iterations: int

    @classmethod
    def from_prop(cls, p):
        g = Vector((p.gravity_dir[0], p.gravity_dir[1], p.gravity_dir[2]))
        if g.length <= 1e-10:
            g = Vector((0.0, 0.0, -1.0))
        else:
            g.normalize()

        axis = Vector((p.axis_scale[0], p.axis_scale[1], p.axis_scale[2]))
        axis.x = max(1e-6, axis.x)
        axis.y = max(1e-6, axis.y)
        axis.z = max(1e-6, axis.z)

        return cls(
            id=p.id,
            name=p.name or p.id,
            center_world=Vector((p.center_world[0], p.center_world[1], p.center_world[2])),
            radius=max(1e-6, float(p.radius)),
            shape=str(p.shape),
            axis_scale=axis,
            resolution=max(8, int(p.resolution)),
            gravity_dir=g,
            sag_strength=max(0.0, float(p.sag_strength)),
            sag_limit=max(0.0, float(p.sag_limit)),
            attach_target_type=str(p.attach_target_type),
            attach_target_id=str(p.attach_target_id),
            attach_target_object_name=str(p.attach_target_object_name),
            control_point_world=Vector((p.control_point_world[0], p.control_point_world[1], p.control_point_world[2])),
            stiffness=max(0.0, min(1.0, float(p.stiffness))),
            iterations=max(1, int(p.iterations)),
        )
