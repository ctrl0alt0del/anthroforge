import math
from mathutils import Vector
from .base import ShapeStrategy

class EllipsoidShape(ShapeStrategy):

    def __init__(self, radii=(1.0, 1.0, 1.0), resolution=8):
        self.radii = radii
        self.resolution = resolution

    def get_attach_params(self):
        params = []
        for i in range(self.resolution):
            theta = (2 * math.pi * i) / self.resolution
            for j in range(1, self.resolution):
                phi = (math.pi * j) / self.resolution
                params.append((theta, phi))
        return params

    def compute_local_point(self, param):
        theta, phi = param
        rx, ry, rz = self.radii

        x = rx * math.sin(phi) * math.cos(theta)
        y = ry * math.sin(phi) * math.sin(theta)
        z = rz * math.cos(phi)

        return Vector((x, y, z))

    def render_debug(self, scp_matrix):
        if debug_name in bpy.data.objects:
            obj = bpy.data.objects[debug_name]
        else:
            mesh = bpy.data.meshes.new(debug_name + "_mesh")
            obj = bpy.data.objects.new(debug_name, mesh)
            bpy.context.scene.collection.objects.link(obj)

            bm = bmesh.new()
            bmesh.ops.create_uvsphere(
                bm,
                u_segments=self.resolution,
                v_segments=self.resolution,
                diameter=1.0
            )
            bm.to_mesh(mesh)
            bm.free()

            obj.display_type = 'WIRE'
            obj.hide_render = True

        obj.matrix_world = scp_matrix
        obj.scale = self.radii

        return obj
