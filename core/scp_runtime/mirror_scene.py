import os

import bpy
from mathutils import Matrix, Vector

from ..deps.runtime_trace import trace_line
from ..utils import depsgraph_for_scene, update_scene_view_layer
from ..visualization.mirror_objects import remove_obj
from .common import as_axis, as_id
from .runtime_state import mirror_effective_axis, mirror_source_id, mirror_status
from .tree import children_map


def _axis_to_scale(axis):
    axis = as_axis(axis)
    return (1.0, -1.0, 1.0) if axis == "Y" else ((1.0, 1.0, -1.0) if axis == "Z" else (-1.0, 1.0, 1.0))


def _mirror_matrix(axis="X", origin=(0.0, 0.0, 0.0)):
    origin_vec = origin if isinstance(origin, Vector) else Vector(origin)
    sx, sy, sz = _axis_to_scale(axis)
    return Matrix.Translation(origin_vec) @ Matrix.Diagonal((sx, sy, sz, 1.0)) @ Matrix.Translation(-origin_vec)


def _axis_index(axis):
    return {"Y": 1, "Z": 2}.get(as_axis(axis), 0)


def _unit_axis(index):
    return Vector((1.0 if index == 0 else 0.0, 1.0 if index == 1 else 0.0, 1.0 if index == 2 else 0.0))


def _signed_trs(target, axis):
    linear = target.to_3x3()
    cols = [linear.col[i].copy() for i in range(3)]
    scale = [col.length or 1.0 for col in cols]
    basis = [col / scale[i] if scale[i] > 1e-8 else _unit_axis(i) for i, col in enumerate(cols)]
    if Matrix(basis).transposed().determinant() < 0.0:
        basis[_axis_index(axis)], scale[_axis_index(axis)] = -basis[_axis_index(axis)], -scale[_axis_index(axis)]
    return target.to_translation(), Matrix(basis).transposed().to_quaternion(), Vector(scale)


def _set_rotation(obj, quat):
    if obj.rotation_mode == "QUATERNION":
        obj.rotation_quaternion = quat
        return
    if obj.rotation_mode == "AXIS_ANGLE":
        angle, axis = quat.to_axis_angle()
        obj.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
        return
    obj.rotation_euler = quat.to_euler(obj.rotation_mode)


def _apply_world_target(obj, target_world, axis):
    if obj.parent is not None:
        obj.parent = None
    obj.matrix_parent_inverse.identity()
    loc, quat, scale = _signed_trs(target_world, axis)
    obj.location, obj.scale = loc, scale
    _set_rotation(obj, quat)


def _mirror_trace_enabled():
    raw = str(os.environ.get("AF_MIRROR_TRACE", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _mirror_trace_names():
    raw = str(os.environ.get("AF_MIRROR_TRACE_NAMES", "") or "")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _trace_match(obj):
    names = _mirror_trace_names()
    return bool(_mirror_trace_enabled() and obj and (not names or str(obj.name).lower() in names))


def _scope_ids(values):
    return None if values is None else {as_id(v) for v in set(values or ()) if as_id(v)}


def _expanded_target_ids(scp_by_id, values):
    ids = _scope_ids(values)
    return None if ids is None else _expand_scope(children_map(scp_by_id), ids)


def _expand_scope(kids, seed_ids):
    out, stack = set(seed_ids or set()), list(seed_ids or set())
    while stack:
        sid = stack.pop()
        for child_id in kids.get(sid, ()):
            if child_id not in out:
                out.add(child_id)
                stack.append(child_id)
    return out


def _copy_eval_mesh(obj, depsgraph):
    try:
        return bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), depsgraph=depsgraph)
    except RuntimeError:
        return None


def _trace_mirror(stage, source_obj, mirror_obj):
    if _trace_match(mirror_obj):
        trace_line(f"mirror {stage} src={source_obj.name} mir={mirror_obj.name}")


class MirrorSceneSync:
    def __init__(self, sync, root, scene, scp_by_id, target_scp_ids=None):
        self.sync = sync
        self.root = root
        self.scene = scene
        self.scp_by_id = scp_by_id
        self.target_ids = _expanded_target_ids(self.scp_by_id, target_scp_ids)
        self.affected_ids = set() if self.target_ids is None else set(self.target_ids)
        self.desired_ids = set()
        self.depsgraph = None
        self.mirror_col = sync._get_mirror_collection(scene)

    def run(self):
        trace_line(f"mirror run targets={sorted(self.target_ids or set())}") if _mirror_trace_enabled() else None
        update_scene_view_layer(self.scene)
        self.depsgraph = depsgraph_for_scene(self.scene)
        for sid, scp in self.scp_by_id.items():
            self._sync_target(sid, scp)
        self._remove_stale()
        update_scene_view_layer(self.scene)

    def _sync_target(self, sid, scp):
        if not self._should_sync_target(sid, scp):
            return
        self._rebuild_target_mirror(sid, scp)

    def _should_sync_target(self, sid, scp):
        source_id = mirror_source_id(scp)
        status_ok = mirror_status(scp) == "TARGET"
        in_scope = not self.target_ids or sid in self.target_ids or source_id in self.target_ids
        self.affected_ids.add(sid) if status_ok and in_scope else None
        return bool(status_ok and in_scope and source_id in self.scp_by_id)

    def _rebuild_target_mirror(self, sid, scp):
        metadata = self._mirror_authoring_metadata(sid)
        self._remove_target_cluster(sid)
        mirror_obj = self._build_target_mirror(sid, scp)
        if mirror_obj is not None:
            for key, value in metadata.items():
                mirror_obj[key] = value
        self.desired_ids.add(sid) if mirror_obj is not None else None

    def _mirror_authoring_metadata(self, sid):
        objects = [obj for obj in self.scene.objects if self._is_target_mirror(obj, sid)]
        if len(objects) != 1:
            return {}
        obj = objects[0]
        keys = ('af_authoring_id', 'af_authoring_root_id', 'af_anatomical_side')
        return {key: obj[key] for key in keys if key in obj}

    def _build_target_mirror(self, sid, scp):
        source_obj = self._target_geometry(scp)
        mesh = None if source_obj is None else _copy_eval_mesh(source_obj, self.depsgraph)
        if mesh is None:
            return None
        obj = bpy.data.objects.new(f"{source_obj.name}_AF_MIR", mesh)
        self.mirror_col.objects.link(obj)
        self._copy_object_state(source_obj, obj)
        self._tag_mirror_object(obj, sid)
        self._apply_object_mirror(scp, source_obj, obj)
        _trace_mirror("build", source_obj, obj)
        return obj

    def _target_geometry(self, scp):
        obj = getattr(scp, "geometry_object_ref", None)
        return None if obj is None or obj.type == "EMPTY" else obj

    def _copy_object_state(self, source_obj, obj):
        obj.color = source_obj.color
        obj.display_type = source_obj.display_type
        obj.show_all_edges = source_obj.show_all_edges
        obj.show_in_front = source_obj.show_in_front
        obj.show_wire = source_obj.show_wire
        obj.hide_render = source_obj.hide_render

    def _tag_mirror_object(self, obj, sid):
        self._clear_mirror_tags(obj)
        obj["af_root_name"] = self.root.name
        obj["af_scp_mirror"] = True
        obj["af_source_scp_id"] = sid
        obj["af_scp_geometry"] = True
        obj["af_scp_transform"] = False
        obj.hide_select = True

    def _clear_mirror_tags(self, obj):
        for key in ("af_scp_bound", "af_scp_bound_id", "af_scp_id", "af_scp_transform", "af_scp_geometry", "af_scp_mirror", "af_source_scp_id", "af_source_bound_id"):
            obj.pop(key, None)

    def _apply_object_mirror(self, scp, source_obj, mirror_obj):
        axis, origin = self._mirror_rule(scp)
        target_world = _mirror_matrix(axis=axis, origin=origin) @ source_obj.matrix_world
        _apply_world_target(mirror_obj, target_world, axis)

    def _mirror_rule(self, scp):
        source_scp = self.scp_by_id[mirror_source_id(scp)]
        axis = self._mirror_axis(scp, source_scp)
        origin = tuple(getattr(source_scp, "mirror_origin", (0.0, 0.0, 0.0)))
        return axis, origin

    def _mirror_axis(self, scp, source_scp):
        axis = mirror_effective_axis(scp)
        return axis if axis in {"X", "Y", "Z"} else as_axis(getattr(source_scp, "mirror_axis", "X"))

    def _remove_target_cluster(self, sid):
        for obj in tuple(self.scene.objects):
            remove_obj(obj) if self._is_target_mirror(obj, sid) else None

    def _is_target_mirror(self, obj, sid):
        same_root = obj.get("af_root_name") == self.root.name
        return bool(obj.get("af_scp_mirror") and same_root and as_id(obj.get("af_source_scp_id")) == sid)

    def _remove_stale(self):
        for obj in tuple(self.scene.objects):
            remove_obj(obj) if not self._should_keep_existing(obj) else None

    def _should_keep_existing(self, obj):
        sid = as_id(obj.get("af_source_scp_id"))
        ours = obj.get("af_scp_mirror") and obj.get("af_root_name") == self.root.name
        return bool(not ours or sid in self.desired_ids or (self.target_ids and sid not in self.affected_ids))


def sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=None):
    MirrorSceneSync(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids).run()
