# core/shapes/ellipsoid.py
import math
import bpy
import bmesh
from mathutils import Vector
from .base import ShapeStrategy
from .deformers import MirrorDeformer, ResolutionDeformer
from .registry import ShapeRegistry


class _EllipsoidClipDeformer:
    priority = 20

    def forward(self, p, _shape):
        return p

    def inverse(self, p, _shape):
        return p

    @staticmethod
    def _plane_defs(shape):
        if not bool(getattr(shape, "clip_enabled", False)):
            return []
        out = []
        for i in (1, 2):
            if not bool(getattr(shape, f"clip{i}_enabled", False)):
                continue
            n = Vector(getattr(shape, f"clip{i}_normal", (1.0, 0.0, 0.0)))
            if n.length <= 1e-9:
                continue
            n.normalize()
            off = float(getattr(shape, f"clip{i}_offset", 0.0))
            keep_side = str(getattr(shape, f"clip{i}_keep_side", "POS"))
            keep_pos = (keep_side != "NEG")
            out.append((n, off, keep_pos))
        return out

    def is_kept(self, p, shape):
        for n, off, keep_pos in self._plane_defs(shape):
            s = n.dot(p) - off
            if keep_pos:
                if s < 0.0:
                    return False
            else:
                if s > 0.0:
                    return False
        return True

    def project_to_boundary(self, p, shape):
        q = p.copy()
        for n, off, keep_pos in self._plane_defs(shape):
            s = n.dot(q) - off
            if keep_pos:
                if s < 0.0:
                    q -= n * s
            else:
                if s > 0.0:
                    q -= n * s
        return q


class EllipsoidShape(ShapeStrategy):
    type_id = "ELLIPSOID"
    label = "Ellipsoid"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    _MIRROR = MirrorDeformer()
    _CLIP = _EllipsoidClipDeformer()
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
        return cls(
            radii=tuple(scp_prop.ellipsoid_radii),
            resolution=scp_prop.ellipsoid_resolution,
            clip_enabled=bool(getattr(scp_prop, "ellipsoid_clip_enabled", False)),
            clip1_enabled=bool(getattr(scp_prop, "ellipsoid_clip1_enabled", False)),
            clip1_normal=tuple(getattr(scp_prop, "ellipsoid_clip1_normal", (1.0, 0.0, 0.0))),
            clip1_offset=float(getattr(scp_prop, "ellipsoid_clip1_offset", 0.0)),
            clip1_keep_side=str(getattr(scp_prop, "ellipsoid_clip1_keep_side", "POS")),
            clip2_enabled=bool(getattr(scp_prop, "ellipsoid_clip2_enabled", False)),
            clip2_normal=tuple(getattr(scp_prop, "ellipsoid_clip2_normal", (-1.0, 0.0, 0.0))),
            clip2_offset=float(getattr(scp_prop, "ellipsoid_clip2_offset", 0.0)),
            clip2_keep_side=str(getattr(scp_prop, "ellipsoid_clip2_keep_side", "POS")),
        )

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
        layout.prop(scene, "af_new_ellipsoid_clip_enabled")
        ccol = layout.column()
        ccol.enabled = bool(scene.af_new_ellipsoid_clip_enabled)
        ccol.prop(scene, "af_new_ellipsoid_clip1_enabled")
        p1 = ccol.column()
        p1.enabled = bool(scene.af_new_ellipsoid_clip1_enabled)
        p1.prop(scene, "af_new_ellipsoid_clip1_normal")
        p1.prop(scene, "af_new_ellipsoid_clip1_offset")
        p1.prop(scene, "af_new_ellipsoid_clip1_keep_side")
        ccol.prop(scene, "af_new_ellipsoid_clip2_enabled")
        p2 = ccol.column()
        p2.enabled = bool(scene.af_new_ellipsoid_clip2_enabled)
        p2.prop(scene, "af_new_ellipsoid_clip2_normal")
        p2.prop(scene, "af_new_ellipsoid_clip2_offset")
        p2.prop(scene, "af_new_ellipsoid_clip2_keep_side")

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        scp_prop.ellipsoid_radii = scene.af_new_ellipsoid_radii
        scp_prop.ellipsoid_resolution = scene.af_new_ellipsoid_resolution
        scp_prop.ellipsoid_clip_enabled = bool(scene.af_new_ellipsoid_clip_enabled)
        scp_prop.ellipsoid_clip1_enabled = bool(scene.af_new_ellipsoid_clip1_enabled)
        scp_prop.ellipsoid_clip1_normal = tuple(scene.af_new_ellipsoid_clip1_normal)
        scp_prop.ellipsoid_clip1_offset = float(scene.af_new_ellipsoid_clip1_offset)
        scp_prop.ellipsoid_clip1_keep_side = str(scene.af_new_ellipsoid_clip1_keep_side)
        scp_prop.ellipsoid_clip2_enabled = bool(scene.af_new_ellipsoid_clip2_enabled)
        scp_prop.ellipsoid_clip2_normal = tuple(scene.af_new_ellipsoid_clip2_normal)
        scp_prop.ellipsoid_clip2_offset = float(scene.af_new_ellipsoid_clip2_offset)
        scp_prop.ellipsoid_clip2_keep_side = str(scene.af_new_ellipsoid_clip2_keep_side)

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        col = layout.column()
        col.enabled = not readonly
        col.prop(scp_prop, "ellipsoid_radii")
        col.prop(scp_prop, "ellipsoid_resolution")
        col.prop(scp_prop, "ellipsoid_clip_enabled")
        ccol = col.column()
        ccol.enabled = bool(scp_prop.ellipsoid_clip_enabled)
        ccol.prop(scp_prop, "ellipsoid_clip1_enabled")
        p1 = ccol.column()
        p1.enabled = bool(scp_prop.ellipsoid_clip1_enabled)
        p1.prop(scp_prop, "ellipsoid_clip1_normal")
        p1.prop(scp_prop, "ellipsoid_clip1_offset")
        p1.prop(scp_prop, "ellipsoid_clip1_keep_side")
        ccol.prop(scp_prop, "ellipsoid_clip2_enabled")
        p2 = ccol.column()
        p2.enabled = bool(scp_prop.ellipsoid_clip2_enabled)
        p2.prop(scp_prop, "ellipsoid_clip2_normal")
        p2.prop(scp_prop, "ellipsoid_clip2_offset")
        p2.prop(scp_prop, "ellipsoid_clip2_keep_side")

    def get_deformers(self):
        return [self._MIRROR, self._CLIP, self._RESOLUTION]

    def get_attach_params(self):
        params = []
        for i in range(self.resolution):
            theta = (2 * math.pi * i) / self.resolution
            for j in range(1, self.resolution):
                phi = (math.pi * j) / self.resolution
                p = self._compute_base_local_point(theta, phi)
                if self._CLIP.is_kept(p, self):
                    params.append((theta, phi))
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
        if not self._CLIP.is_kept(p, self):
            p = self._CLIP.project_to_boundary(p, self)
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
        base = self._compute_base_local_point(theta, phi)
        return base if self._CLIP.is_kept(base, self) else self._CLIP.project_to_boundary(base, self)

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
        bm = self._build_ellipsoid_bmesh()
        self._apply_clip_planes(bm)
        bm.to_mesh(mesh)
        bm.free()
        self._finalize_proxy_object(obj, mesh)

    def _build_ellipsoid_bmesh(self):
        rx, ry, rz = self.radii
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(
            bm,
            u_segments=max(8, int(self.resolution) * 2),
            v_segments=max(4, int(self.resolution)),
            radius=1.0,
        )
        bmesh.ops.scale(bm, vec=(rx, ry, rz), verts=bm.verts)
        return bm

    def _finalize_proxy_object(self, obj, mesh):
        mesh.update()
        obj.display_type = "SOLID"
        obj.hide_render = False
        obj.scale = (1.0, 1.0, 1.0)

    def _apply_clip_planes(self, bm):
        if not bool(self.clip_enabled):
            return
        for n, off, keep_pos in self._CLIP._plane_defs(self):
            self._apply_single_clip_plane(bm, n, off, keep_pos)

    def _apply_single_clip_plane(self, bm, n, off, keep_pos):
        plane_co = n * off
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(
            bm,
            geom=geom,
            plane_co=plane_co,
            plane_no=n,
            clear_inner=bool(keep_pos),
            clear_outer=not bool(keep_pos),
            dist=1e-6,
        )
        boundary = [e for e in bm.edges if e.is_boundary]
        if not boundary:
            return
        try:
            bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
        except Exception:
            pass


ShapeRegistry.register(EllipsoidShape)
