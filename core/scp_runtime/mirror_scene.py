from mathutils import Matrix, Vector

from ..visualization.mirror_objects import clone_native_object, remap_object_cluster_parents, remap_object_cluster_refs, remove_obj
from .bound_objects import iter_bound_objects
from .common import as_axis, as_id
from .runtime_state import mirror_effective_axis, mirror_source_id, mirror_status


def _axis_to_scale(axis):
    axis = as_axis(axis)
    return (1.0, -1.0, 1.0) if axis == "Y" else ((1.0, 1.0, -1.0) if axis == "Z" else (-1.0, 1.0, 1.0))


def _mirror_matrix(axis="X", origin=(0.0, 0.0, 0.0)):
    origin_vec = origin if isinstance(origin, Vector) else Vector(origin)
    sx, sy, sz = _axis_to_scale(axis)
    return Matrix.Translation(origin_vec) @ Matrix.Diagonal((sx, sy, sz, 1.0)) @ Matrix.Translation(-origin_vec)


def _bound_pairs(scp):
    return tuple(iter_bound_objects(scp))


class MirrorSceneSync:
    def __init__(self, sync, root, scene, scp_by_id, target_scp_ids=None):
        self.sync = sync
        self.root = root
        self.scene = scene
        self.scp_by_id = scp_by_id
        self.target_ids = None if target_scp_ids is None else {as_id(v) for v in set(target_scp_ids)}
        self.affected_ids = set() if self.target_ids is None else set(self.target_ids)
        self.desired_ids = set()
        self.mirror_col = sync._get_mirror_collection(scene)

    def run(self):
        for sid, scp in self.scp_by_id.items():
            self._sync_target(sid, scp)
        self._remove_stale()

    def _sync_target(self, sid, scp):
        if not self._should_sync_target(sid, scp) or not _bound_pairs(scp):
            return
        self._rebuild_target_cluster(sid, scp)
        self.desired_ids.add(sid)

    def _should_sync_target(self, sid, scp):
        source_id = mirror_source_id(scp)
        status_ok = mirror_status(scp) == "TARGET"
        in_scope = not self.target_ids or sid in self.target_ids or source_id in self.target_ids
        self.affected_ids.add(sid) if status_ok and in_scope else None
        return bool(status_ok and in_scope and source_id in self.scp_by_id)

    def _rebuild_target_cluster(self, sid, scp):
        self._remove_target_cluster(sid)
        clones = self._clone_bound_cluster(sid, scp)
        remap_object_cluster_refs(clones)
        remap_object_cluster_parents(clones)
        self._apply_cluster_mirror(scp, clones)

    def _clone_bound_cluster(self, sid, scp):
        clones = {}
        for entry, obj in _bound_pairs(scp):
            clones[obj] = self._clone_bound_object(sid, scp, entry.id, obj)
        return clones

    def _clone_bound_object(self, sid, scp, bound_id, obj):
        clone = clone_native_object(self.mirror_col, obj, f"{obj.name}_AF_MIR")
        self._tag_mirror_object(clone, sid, bound_id, scp, obj)
        return clone

    def _tag_mirror_object(self, obj, sid, bound_id, scp, source_obj):
        self._clear_mirror_tags(obj)
        obj["af_root_name"] = self.root.name
        obj["af_scp_mirror"] = True
        obj["af_source_scp_id"] = sid
        obj["af_source_bound_id"] = as_id(bound_id)
        obj["af_scp_geometry"] = source_obj == getattr(scp, "geometry_object_ref", None)
        obj["af_scp_transform"] = source_obj == getattr(scp, "transform_object_ref", None)
        obj.hide_select = True

    def _clear_mirror_tags(self, obj):
        for key in ("af_scp_bound", "af_scp_bound_id", "af_scp_id", "af_scp_transform", "af_scp_geometry", "af_scp_mirror", "af_source_scp_id", "af_source_bound_id"):
            obj.pop(key, None)

    def _apply_cluster_mirror(self, scp, clones):
        axis, origin = self._mirror_rule(scp)
        for source_obj, clone in clones.items():
            clone.matrix_world = _mirror_matrix(axis=axis, origin=origin) @ source_obj.matrix_world

    def _mirror_rule(self, scp):
        source_scp = self.scp_by_id[mirror_source_id(scp)]
        axis = self._mirror_axis(scp, source_scp)
        origin = tuple(getattr(source_scp, "mirror_origin", (0.0, 0.0, 0.0)))
        return axis, origin

    def _mirror_axis(self, scp, source_scp):
        axis = mirror_effective_axis(scp)
        return axis if axis in {"X", "Y", "Z"} else as_axis(getattr(source_scp, "mirror_axis", "X"))

    def _remove_target_cluster(self, sid):
        for obj in list(self.scene.objects):
            remove_obj(obj) if self._is_target_mirror(obj, sid) else None

    def _is_target_mirror(self, obj, sid):
        same_root = obj.get("af_root_name") == self.root.name
        return bool(obj.get("af_scp_mirror") and same_root and as_id(obj.get("af_source_scp_id")) == sid)

    def _remove_stale(self):
        for obj in list(self.scene.objects):
            if not self._should_keep_existing(obj):
                remove_obj(obj)

    def _should_keep_existing(self, obj):
        sid = as_id(obj.get("af_source_scp_id"))
        ours = obj.get("af_scp_mirror") and obj.get("af_root_name") == self.root.name
        return bool(not ours or sid in self.desired_ids or (self.target_ids and sid not in self.affected_ids))


def sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=None):
    MirrorSceneSync(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids).run()
