import bpy
from mathutils import Matrix, Vector

from .common import as_axis, as_id, find_source_scp_obj


def _axis_to_scale(axis):
    axis = as_axis(axis)
    if axis == "Y":
        return (1.0, -1.0, 1.0)
    if axis == "Z":
        return (1.0, 1.0, -1.0)
    return (-1.0, 1.0, 1.0)


def _mirror_matrix(axis="X", origin=(0.0, 0.0, 0.0)):
    origin_vec = origin if isinstance(origin, Vector) else Vector(origin)
    sx, sy, sz = _axis_to_scale(axis)
    return Matrix.Translation(origin_vec) @ Matrix.Diagonal((sx, sy, sz, 1.0)) @ Matrix.Translation(-origin_vec)


def _copy_mesh_data(src_obj, dst_obj):
    if src_obj.type != "MESH" or dst_obj.type != "MESH" or dst_obj.data is None:
        return
    dst_obj.data.clear_geometry()
    dst_obj.data.from_pydata([v.co.copy() for v in src_obj.data.vertices], [], [tuple(p.vertices) for p in src_obj.data.polygons])
    dst_obj.data.update()


class MirrorSceneSync:
    def __init__(self, sync, root, scene, scp_by_id, target_scp_ids=None):
        self.sync = sync
        self.root = root
        self.scene = scene
        self.scp_by_id = scp_by_id
        self.target_ids = None if target_scp_ids is None else {as_id(value) for value in set(target_scp_ids)}
        self.affected_ids = set() if self.target_ids is None else set(self.target_ids)
        self.desired_ids = set()
        self.mirror_col = sync._get_mirror_collection(scene)

    def run(self):
        for sid, scp in self.scp_by_id.items():
            self._sync_target(sid, scp)
        self._remove_stale()

    def _sync_target(self, sid, scp):
        if not self._should_sync_target(sid, scp):
            return
        source_obj = find_source_scp_obj(self.scene, self.root.name, sid)
        if source_obj is None:
            return
        mirror_obj = self._ensure_mirror_object(sid, source_obj)
        self._apply_mirror_object(mirror_obj, scp, source_obj)
        self.desired_ids.add(sid)

    def _should_sync_target(self, sid, scp):
        if as_id(getattr(scp, "mirror_status", "NONE")).upper() != "TARGET":
            return False
        source_id = as_id(getattr(scp, "mirror_source_id", ""))
        if self.target_ids and sid not in self.target_ids and source_id not in self.target_ids:
            return False
        self.affected_ids.add(sid)
        return as_id(getattr(scp, "mirror_source_id", "")) in self.scp_by_id

    def _ensure_mirror_object(self, sid, source_obj):
        mirror_obj = self.sync._find_mirror_object(self.scene, self.root.name, sid)
        if mirror_obj is not None:
            return mirror_obj
        mesh = bpy.data.meshes.new(f"{source_obj.name}_AF_MIRROR_MESH")
        mirror_obj = bpy.data.objects.new(f"{source_obj.name}_AF_MIR", mesh)
        self.mirror_col.objects.link(mirror_obj)
        self._tag_mirror_object(mirror_obj, sid)
        return mirror_obj

    def _tag_mirror_object(self, mirror_obj, sid):
        mirror_obj["af_scp"] = True
        mirror_obj["af_scp_mirror"] = True
        mirror_obj["af_root_name"] = self.root.name
        mirror_obj["af_source_scp_id"] = sid
        mirror_obj.hide_select = True

    def _apply_mirror_object(self, mirror_obj, scp, source_obj):
        source_scp = self.scp_by_id[as_id(getattr(scp, "mirror_source_id", ""))]
        axis = self._mirror_axis(scp, source_scp)
        origin = tuple(getattr(source_scp, "mirror_origin", (0.0, 0.0, 0.0)))
        _copy_mesh_data(source_obj, mirror_obj)
        mirror_obj.matrix_world = _mirror_matrix(axis=axis, origin=origin) @ source_obj.matrix_world
        mirror_obj["af_source_scp_id"] = as_id(getattr(scp, "id", ""))
        mirror_obj["af_root_name"] = self.root.name

    def _mirror_axis(self, scp, source_scp):
        axis = as_axis(getattr(scp, "mirror_effective_axis", "X"))
        return axis if axis in {"X", "Y", "Z"} else as_axis(getattr(source_scp, "mirror_axis", "X"))

    def _remove_stale(self):
        for obj in list(self.scene.objects):
            if self._should_keep_existing(obj):
                continue
            self._remove_object(obj)

    def _should_keep_existing(self, obj):
        sid = as_id(obj.get("af_source_scp_id"))
        if not obj.get("af_scp_mirror") or obj.get("af_root_name") != self.root.name:
            return True
        if sid in self.desired_ids:
            return True
        return bool(self.target_ids and sid not in self.affected_ids)

    def _remove_object(self, obj):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0 and isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)


def sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=None):
    MirrorSceneSync(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids).run()
