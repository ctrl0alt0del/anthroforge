# core/shapes/ellipsoid.py
import math
import bpy
import bmesh
from mathutils import Vector
from .base import ShapeStrategy
from .deformers import ShapeSizeDeformer, ResolutionDeformer
from .registry import ShapeRegistry


class EllipsoidShape(ShapeStrategy):
    type_id = "ELLIPSOID"
    label = "Ellipsoid"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    _SIZE = ShapeSizeDeformer()
    _RESOLUTION = ResolutionDeformer()

    def __init__(
        self,
        radii=(1.0, 1.0, 1.0),
        resolution=8,
        clip_enabled=False,
        clip1_enabled=False,
        clip1_normal=(1.0, 0.0, 0.0),
        clip1_offset=0.0,
        clip1_keep_side="POS",
        clip2_enabled=False,
        clip2_normal=(-1.0, 0.0, 0.0),
        clip2_offset=0.0,
        clip2_keep_side="POS",
    ):
        self.radii = radii
        self.resolution = resolution
        self.clip_enabled = bool(clip_enabled)
        self.clip1_enabled = bool(clip1_enabled)
        self.clip1_normal = tuple(clip1_normal)
        self.clip1_offset = float(clip1_offset)
        self.clip1_keep_side = str(clip1_keep_side)
        self.clip2_enabled = bool(clip2_enabled)
        self.clip2_normal = tuple(clip2_normal)
        self.clip2_offset = float(clip2_offset)
        self.clip2_keep_side = str(clip2_keep_side)

    @classmethod
    def from_scp_prop(cls, scp_prop):
        shape = cls(
            radii=tuple(scp_prop.ellipsoid_radii),
            resolution=scp_prop.ellipsoid_resolution,
            clip_enabled=False,
            clip1_enabled=False,
            clip1_normal=(1.0, 0.0, 0.0),
            clip1_offset=0.0,
            clip1_keep_side="POS",
            clip2_enabled=False,
            clip2_normal=(-1.0, 0.0, 0.0),
            clip2_offset=0.0,
            clip2_keep_side="POS",
        )
        return cls.hydrate_from_scp_prop(shape, scp_prop)

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        scp_prop.ellipsoid_radii = (1.0, 1.0, 1.0)
        scp_prop.ellipsoid_resolution = 8
        scp_prop.ellipsoid_clip_enabled = False
        scp_prop.ellipsoid_clip1_enabled = False
        scp_prop.ellipsoid_clip1_normal = (1.0, 0.0, 0.0)
        scp_prop.ellipsoid_clip1_offset = 0.0
        scp_prop.ellipsoid_clip1_keep_side = "POS"
        scp_prop.ellipsoid_clip2_enabled = False
        scp_prop.ellipsoid_clip2_normal = (-1.0, 0.0, 0.0)
        scp_prop.ellipsoid_clip2_offset = 0.0
        scp_prop.ellipsoid_clip2_keep_side = "POS"

    @classmethod
    def register_scene_props(cls):
        cls._register_base_scene_props()
        cls._register_clip_scene_props()

    @classmethod
    def _register_base_scene_props(cls):
        bpy.types.Scene.af_new_ellipsoid_radii = bpy.props.FloatVectorProperty(
            name="Radii", size=3, default=(1.0, 1.0, 1.0), min=0.001, subtype="XYZ"
        )
        bpy.types.Scene.af_new_ellipsoid_resolution = bpy.props.IntProperty(
            name="Resolution", default=8, min=3, max=128
        )
        bpy.types.Scene.af_new_ellipsoid_clip_enabled = bpy.props.BoolProperty(
            name="Enable Clipping", default=False
        )

    @classmethod
    def _register_clip_scene_props(cls):
        bpy.types.Scene.af_new_ellipsoid_clip1_enabled = bpy.props.BoolProperty(
            name="Clip Plane 1", default=False
        )
        bpy.types.Scene.af_new_ellipsoid_clip1_normal = bpy.props.FloatVectorProperty(
            name="Plane 1 Normal", size=3, subtype="XYZ", default=(1.0, 0.0, 0.0)
        )
        bpy.types.Scene.af_new_ellipsoid_clip1_offset = bpy.props.FloatProperty(
            name="Plane 1 Offset", default=0.0
        )
        bpy.types.Scene.af_new_ellipsoid_clip1_keep_side = bpy.props.EnumProperty(
            name="Plane 1 Keep",
            items=[("POS", "Positive Side", ""), ("NEG", "Negative Side", "")],
            default="POS",
        )
        bpy.types.Scene.af_new_ellipsoid_clip2_enabled = bpy.props.BoolProperty(
            name="Clip Plane 2", default=False
        )
        bpy.types.Scene.af_new_ellipsoid_clip2_normal = bpy.props.FloatVectorProperty(
            name="Plane 2 Normal", size=3, subtype="XYZ", default=(-1.0, 0.0, 0.0)
        )
        bpy.types.Scene.af_new_ellipsoid_clip2_offset = bpy.props.FloatProperty(
            name="Plane 2 Offset", default=0.0
        )
        bpy.types.Scene.af_new_ellipsoid_clip2_keep_side = bpy.props.EnumProperty(
            name="Plane 2 Keep",
            items=[("POS", "Positive Side", ""), ("NEG", "Negative Side", "")],
            default="POS",
        )

    @classmethod
    def unregister_scene_props(cls):
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_radii"):
            del bpy.types.Scene.af_new_ellipsoid_radii
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_resolution"):
            del bpy.types.Scene.af_new_ellipsoid_resolution
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip_enabled"):
            del bpy.types.Scene.af_new_ellipsoid_clip_enabled
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip1_enabled"):
            del bpy.types.Scene.af_new_ellipsoid_clip1_enabled
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip1_normal"):
            del bpy.types.Scene.af_new_ellipsoid_clip1_normal
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip1_offset"):
            del bpy.types.Scene.af_new_ellipsoid_clip1_offset
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip1_keep_side"):
            del bpy.types.Scene.af_new_ellipsoid_clip1_keep_side
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip2_enabled"):
            del bpy.types.Scene.af_new_ellipsoid_clip2_enabled
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip2_normal"):
            del bpy.types.Scene.af_new_ellipsoid_clip2_normal
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip2_offset"):
            del bpy.types.Scene.af_new_ellipsoid_clip2_offset
        if hasattr(bpy.types.Scene, "af_new_ellipsoid_clip2_keep_side"):
            del bpy.types.Scene.af_new_ellipsoid_clip2_keep_side

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

    def get_deformers(self):
        # Explicit stack order:
        # Shape Size -> Resolution -> Dynamic Deformers -> Control
        return [self._SIZE, self._RESOLUTION]

    def get_attach_params(self):
        params = []
        for i in range(self.resolution):
            theta = (2 * math.pi * i) / self.resolution
            for j in range(1, self.resolution):
                params.append((theta, (math.pi * j) / self.resolution))
        if not params:
            params.append((0.0, math.pi * 0.5))
        return params

    def _compute_base_local_point(self, theta, phi):
        rx, ry, rz = self.radii
        x = rx * math.sin(phi) * math.cos(theta)
        y = ry * math.sin(phi) * math.sin(theta)
        z = rz * math.cos(phi)
        return Vector((x, y, z))

    def compute_local_point(self, param):
        theta, phi = param
        p = self._compute_base_local_point(theta, phi)
        return self.apply_point_deformers(p)

    def sample_attachment_frame_local(self, param):
        theta, phi = self._parse_attach_param(param)
        base = self._attachment_base(theta, phi)
        origin = self.apply_point_deformers(base.copy())
        normal = self._stable_normal(base, origin)
        tangent = self._stable_tangent(theta, phi, normal)
        return origin, tangent, normal

    def _parse_attach_param(self, param):
        try:
            theta, phi = param
            return float(theta), float(phi)
        except Exception:
            return 0.0, math.pi * 0.5

    def _attachment_base(self, theta, phi):
        return self._compute_base_local_point(theta, phi)

    def _stable_normal(self, base, origin):
        normal = self._surface_normal(base)
        if normal.length <= 1e-8:
            normal = origin.copy()
        if normal.length <= 1e-8:
            return Vector((0.0, 0.0, 1.0))
        normal.normalize()
        return normal

    def _stable_tangent(self, theta, phi, normal):
        tangent = self._surface_tangent(theta, phi)
        if tangent.length <= 1e-8:
            tangent = normal.cross(Vector((0.0, 0.0, 1.0)))
        if tangent.length <= 1e-8:
            tangent = normal.cross(Vector((0.0, 1.0, 0.0)))
        if tangent.length <= 1e-8:
            return Vector((1.0, 0.0, 0.0))
        tangent.normalize()
        return tangent

    def _surface_normal(self, base):
        rx, ry, rz = self.radii
        nx = (base.x / max(1e-8, rx * rx))
        ny = (base.y / max(1e-8, ry * ry))
        nz = (base.z / max(1e-8, rz * rz))
        return self.apply_point_deformers(Vector((nx, ny, nz)))

    def _surface_tangent(self, theta, phi):
        rx, ry, _rz = self.radii
        dtheta = Vector((
            -rx * math.sin(phi) * math.sin(theta),
            ry * math.sin(phi) * math.cos(theta),
            0.0,
        ))
        return self.apply_point_deformers(dtheta)

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
        verts, faces = self._base_mesh_data()
        verts, faces = self.apply_geometry_deformers(verts, faces)
        mesh.clear_geometry()
        mesh.from_pydata([(v.x, v.y, v.z) for v in verts], [], faces)
        self._finalize_proxy_object(obj, mesh)

    def _base_mesh_data(self):
        rx, ry, rz = self.radii
        bm = bmesh.new()
        try:
            bmesh.ops.create_uvsphere(
                bm,
                u_segments=max(8, int(self.resolution) * 2),
                v_segments=max(4, int(self.resolution)),
                radius=1.0,
            )
            bmesh.ops.scale(bm, vec=(rx, ry, rz), verts=bm.verts)
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            verts = [v.co.copy() for v in bm.verts]
            faces = [tuple(v.index for v in f.verts) for f in bm.faces]
            return verts, faces
        finally:
            bm.free()

    def _finalize_proxy_object(self, obj, mesh):
        mesh.update()
        obj.display_type = "SOLID"
        obj.hide_render = False
        obj.scale = (1.0, 1.0, 1.0)

ShapeRegistry.register(EllipsoidShape)
