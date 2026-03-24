import bpy
from mathutils import Vector

from .base import ShapeStrategy
from .deformers import MirrorDeformer, ResolutionDeformer
from .registry import ShapeRegistry
from ..assets.scp_mesh_library import load_asset_mesh, enum_items, list_assets


class MeshAssetShape(ShapeStrategy):
    type_id = "MESH_ASSET"
    label = "Mesh Asset"

    proxy_object_type = "MESH"
    proxy_data_type = "MESH"
    supports_fiber_collision = True
    _MIRROR = MirrorDeformer()
    _RESOLUTION = ResolutionDeformer()

    def __init__(self, asset_id="", resolution_hint=0):
        self.asset_id = asset_id or ""
        self.resolution_hint = int(resolution_hint)
        self._cached_verts = []

    @classmethod
    def from_scp_prop(cls, scp_prop):
        return cls(
            asset_id=getattr(scp_prop, "mesh_asset_id", ""),
            resolution_hint=0,
        )

    @classmethod
    def init_scp_prop_defaults(cls, scp_prop):
        if not getattr(scp_prop, "mesh_asset_id", ""):
            items = enum_items()
            first = items[0][0] if items else "__NONE__"
            scp_prop.mesh_asset_id = "" if first == "__NONE__" else first

    @classmethod
    def register_scene_props(cls):
        pass

    @classmethod
    def unregister_scene_props(cls):
        pass

    @classmethod
    def draw_creation_ui(cls, layout, scene):
        assets = list_assets()
        selected = getattr(scene, "af_new_scp_mesh_asset_id", "")

        box = layout.box()
        box.label(text="Mesh Assets")

        if not assets:
            box.label(text="No assets. Register one above.", icon="INFO")
            return

        for a in assets:
            row = box.row(align=True)

            op = row.operator(
                "af.select_mesh_scp_asset",
                text=a["name"],
                emboss=True,
                depress=(a["id"] == selected),
                icon="MESH_DATA",
            )
            op.asset_id = a["id"]

            del_op = row.operator(
                "af.delete_mesh_scp_asset",
                text="",
                icon="TRASH",
                emboss=False,
            )
            del_op.asset_id = a["id"]

        if selected:
            box.label(text=f"Selected: {selected}")

    @classmethod
    def apply_creation_to_scp(cls, scene, scp_prop):
        aid = getattr(scene, "af_new_scp_mesh_asset_id", "")
        if aid == "__NONE__":
            aid = ""
        scp_prop.mesh_asset_id = aid

    @classmethod
    def draw_scp_ui(cls, layout, scp_prop, readonly=False):
        row = layout.row()
        row.enabled = not readonly
        row.prop(scp_prop, "mesh_asset_id", text="Asset")

    def get_deformers(self):
        return [self._MIRROR, self._RESOLUTION]

    def _refresh_vertex_cache_from_obj(self, obj):
        self._cached_verts = []
        if obj is None or obj.type != "MESH" or obj.data is None:
            return
        self._cached_verts = [v.co.copy() for v in obj.data.vertices]

    def _ensure_cached_verts(self):
        # Critical for runtime instances (e.g. solver registry) where ensure_proxy_object
        # may not have run yet.
        if self._cached_verts:
            return
        if not self.asset_id:
            return
        mesh = load_asset_mesh(self.asset_id)
        if mesh is None:
            return
        self._cached_verts = [v.co.copy() for v in mesh.vertices]

    def get_attach_params(self):
        self._ensure_cached_verts()
        if not self._cached_verts:
            return [0]
        return list(range(len(self._cached_verts)))

    def compute_local_point(self, param):
        self._ensure_cached_verts()
        if not self._cached_verts:
            return Vector((0.0, 0.0, 0.0))
        try:
            idx = int(param)
        except Exception:
            idx = 0
        idx = max(0, min(len(self._cached_verts) - 1, idx))
        return self.apply_point_deformers(self._cached_verts[idx].copy())

    def ensure_proxy_object(self, obj):
        if obj.type != "MESH":
            return

        mesh = load_asset_mesh(self.asset_id) if self.asset_id else None
        if mesh is None:
            if obj.data is None:
                obj.data = bpy.data.meshes.new("AF_EMPTY_MESH_ASSET")
            else:
                obj.data.clear_geometry()
                obj.data.update()
            self._refresh_vertex_cache_from_obj(obj)
            return

        if obj.data != mesh:
            obj.data = mesh

        self._refresh_vertex_cache_from_obj(obj)


ShapeRegistry.register(MeshAssetShape)
