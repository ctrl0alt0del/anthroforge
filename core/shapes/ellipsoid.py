# core/shapes/ellipsoid.py
import math
import bpy
import bmesh
from mathutils import Vector
from .base import ShapeStrategy
from .registry import ShapeRegistry


class EllipsoidShape(ShapeStrategy):
    type_id = "ELLIPSOID"
    label = "Ellipsoid"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"

    def __init__(self, radii=(1.0, 1.0, 1.0), resolution=8):
        self.radii = radii
        self.resolution = resolution

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls(
            radii=tuple(scp_prop.ellipsoid_radii),
            resolution=scp_prop.ellipsoid_resolution,
        )

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        scp_prop.ellipsoid_radii = (1.0, 1.0, 1.0)
        scp_prop.ellipsoid_resolution = 8

    @classmethod
    def register_scene_props(cls):
        bpy.types.Scene.af_new_ellipsoid_radii = bpy.props.FloatVectorProperty(
            name="Radii", size=3, default=(1.0, 1.0, 1.0), min=0.001, subtype="XYZ"
        )
        bpy.types.Scene.af_new_ellipsoid_resolution = bpy.props.IntProperty(
            name="Resolution", default=8, min=3, max=128
        )

    @classmethod
    def unregister_scene_props(cls):
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_radii"):
            del bpy.types.Scene.af_new_ellipsoid_radii
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_resolution"):
            del bpy.types.Scene.af_new_ellipsoid_resolution

    @classmethod
    def draw_creation_ui(cls, layout, scene):
        layout.prop(scene, "af_new_ellipsoid_radii")
        layout.prop(scene, "af_new_ellipsoid_resolution")

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        scp_prop.ellipsoid_radii = scene.af_new_ellipsoid_radii
        scp_prop.ellipsoid_resolution = scene.af_new_ellipsoid_resolution

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        col = layout.column()
        col.enabled = not readonly
        col.prop(scp_prop, "ellipsoid_radii")
        col.prop(scp_prop, "ellipsoid_resolution")

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

    def ensure_proxy_object(self, obj):
        """
        Build ellipsoid geometry in mesh data (baked radii),
        leaving object transform for SCP transform only.
        """
        if obj.type != "MESH":
            raise TypeError(f"Ellipsoid proxy must be MESH, got {obj.type}")

        if obj.data is None:
            obj.data = bpy.data.meshes.new(f"{obj.name}_mesh")

        mesh = obj.data
        rx, ry, rz = self.radii

        bm = bmesh.new()
        bmesh.ops.create_uvsphere(
            bm,
            u_segments=max(8, int(self.resolution) * 2),
            v_segments=max(4, int(self.resolution)),
            radius=1.0,
        )
        bmesh.ops.scale(
            bm,
            vec=(rx, ry, rz),
            verts=bm.verts
        )

        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

        obj.display_type = "SOLID"
        obj.hide_render = False

        # Keep transform scale neutral; SCP transform controls world scale
        obj.scale = (1.0, 1.0, 1.0)


ShapeRegistry.register(EllipsoidShape)
