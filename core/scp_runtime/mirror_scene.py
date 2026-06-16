import os

import bpy
from mathutils import Matrix, Vector

from ..deps.runtime_trace import trace_line
from ..utils import update_scene_view_layer
from ..visualization.mirror_objects import clone_native_object, remap_object_cluster_refs, remove_obj
from .bound_objects import iter_bound_objects
from .mirror_clone_prep import prepare_mirror_clone
from .common import as_axis, as_id, is_bound_scp_obj
from .mirror_placement import apply_parent_target, mirror_clone_pairs, mirror_parent_for, mirror_target_worlds
from .runtime_state import mirror_effective_axis, mirror_source_id, mirror_status


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


def _bound_pairs(scp):
    return tuple(iter_bound_objects(scp))


def _mirror_trace_enabled():
    raw = str(os.environ.get("AF_MIRROR_TRACE", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _mirror_trace_names():
    raw = str(os.environ.get("AF_MIRROR_TRACE_NAMES", "") or "")
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


def _trace_match(obj):
    names = _mirror_trace_names()
    return bool(_mirror_trace_enabled() and obj and (not names or str(obj.name).lower() in names))


def _curve_target_name(obj):
    mod = next((m for m in getattr(obj, "modifiers", ()) if m.type == "CURVE" and getattr(m, "object", None)), None)
    return "" if mod is None else str(mod.object.name)


def _hook_mod(obj):
    return next((m for m in getattr(obj, "modifiers", ()) if m.type == "HOOK" and getattr(m, "object", None)), None)


def _curve_hook_dist(obj, target):
    _ = obj
    _ = target
    return None


def _trace_tuple(vec):
    return tuple(round(float(value), 4) for value in vec)


def _trace_obj(stage, obj):
    if not _trace_match(obj):
        return
    hook = _hook_mod(obj)
    target = None if hook is None else hook.object
    dist = None if target is None else _curve_hook_dist(obj, target.matrix_world.to_translation().copy())
    msg = f"mirror {stage} obj={obj.name} parent={'' if obj.parent is None else obj.parent.name} loc={_trace_tuple(obj.location)} scale={_trace_tuple(obj.scale)} curve={_curve_target_name(obj)} hook={'' if target is None else target.name} dist={None if dist is None else round(float(dist), 6)}"
    trace_line(msg)


def _trace_cluster(stage, clones):
    for source_obj, clone_obj in dict(clones or {}).items():
        _trace_obj(f"{stage}.src", source_obj)
        _trace_obj(f"{stage}.mir", clone_obj)


def _ref_sources():
    return (_modifier_pointer_refs,)


def _ref_filters():
    return (_hook_scp_filter,)


def _hook_owners(obj):
    return tuple(owner for owner in getattr(obj, "modifiers", ()) if getattr(owner, "type", "") == "HOOK")


def _bind_state_key(bound_id, owner):
    return (as_id(bound_id), str(getattr(owner, "name", "")), str(getattr(owner, "type", "")))


def _capture_bind_state(bound_id, owner):
    state = {"matrix_inverse": owner.matrix_inverse.copy()} if getattr(owner, "type", "") == "HOOK" else None
    return None if state is None else (_bind_state_key(bound_id, owner), state)


def _restore_bind_state(owner, state):
    if not state or "matrix_inverse" not in state:
        return False
    owner.matrix_inverse = state["matrix_inverse"].copy()
    return True


def _modifier_pointer_refs(source_obj, clone_obj):
    refs = []
    for modifier in getattr(clone_obj, "modifiers", ()):
        refs.extend(_owner_pointer_refs(source_obj, clone_obj, modifier))
    return tuple(refs)


def _owner_pointer_refs(source_obj, clone_obj, owner):
    refs = []
    for prop in getattr(owner.bl_rna, "properties", ()):
        ref = _pointer_ref(source_obj, clone_obj, owner, prop)
        refs.append(ref) if ref else None
    return refs


def _pointer_ref(source_obj, clone_obj, owner, prop):
    key = prop.identifier
    if key == "rna_type" or prop.is_readonly or prop.type != "POINTER":
        return None
    value = getattr(owner, key, None)
    return None if value is None else {"source_obj": source_obj, "clone_obj": clone_obj, "owner": owner, "key": key, "value": value}


def _cluster_refs(clones):
    refs = []
    for source_obj, clone_obj in clones.items():
        for refs_from_source in _ref_sources():
            refs.extend(refs_from_source(source_obj, clone_obj))
    return tuple(refs)


def _is_external_cluster_ref(ref, cluster_objs):
    return ref["value"] not in cluster_objs


def _is_source_bound_ref(obj, root_name):
    return bool(is_bound_scp_obj(obj, root_name) and obj.get("af_scp_bound_id"))


def _hook_scp_filter(ref, root_name):
    owner = ref["owner"]
    return bool(getattr(owner, "type", "") == "HOOK" and ref["key"] == "object" and _is_source_bound_ref(ref["value"], root_name))


def _is_filtered_ref(ref, root_name):
    return any(check(ref, root_name) for check in _ref_filters())


def _is_remappable_ref(ref, root_name, cluster_objs):
    return _is_external_cluster_ref(ref, cluster_objs) and _is_filtered_ref(ref, root_name)


class MirrorSceneSync:
    def __init__(self, sync, root, scene, scp_by_id, target_scp_ids=None):
        self.sync = sync
        self.root = root
        self.scene = scene
        self.scp_by_id = scp_by_id
        self.target_ids = None if target_scp_ids is None else {as_id(v) for v in set(target_scp_ids)}
        self.affected_ids = set() if self.target_ids is None else set(self.target_ids)
        self.desired_ids = set()
        self.bind_state_by_sid = {}
        self.clones_by_sid = {}
        self.pending_bind_refs = []
        self.mirror_col = sync._get_mirror_collection(scene)

    def run(self):
        trace_line(f"mirror run targets={sorted(self.target_ids or set())}") if _mirror_trace_enabled() else None
        for sid, scp in self.scp_by_id.items():
            self._sync_target(sid, scp)
        self._remove_stale()
        self._remap_external_refs()
        self._restore_pending_bind_states()

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
        self.bind_state_by_sid[sid] = self._capture_target_bind_state(sid)
        self._remove_target_cluster(sid)
        clones = self._clone_bound_cluster(sid, scp)
        remap_object_cluster_refs(clones)
        self._apply_cluster_mirror(scp, clones)
        self.clones_by_sid[sid] = clones
        _trace_cluster(f"rebuild[{sid}]", clones)

    def _capture_target_bind_state(self, sid):
        states = {}
        for obj in self._target_mirror_objs(sid):
            bid = as_id(obj.get("af_source_bound_id"))
            for owner in _hook_owners(obj):
                item = _capture_bind_state(bid, owner)
                states[item[0]] = item[1] if item else None
        return states

    def _target_mirror_objs(self, sid):
        return tuple(obj for obj in self.scene.objects if self._is_target_mirror(obj, sid))

    def _clone_bound_cluster(self, sid, scp):
        clones = {}
        for entry, obj in _bound_pairs(scp):
            clones[obj] = self._clone_bound_object(sid, scp, entry.id, obj)
        return clones

    def _clone_bound_object(self, sid, scp, bound_id, obj):
        clone = clone_native_object(self.mirror_col, obj, f"{obj.name}_AF_MIR")
        prepare_mirror_clone(clone)
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
        mirror = _mirror_matrix(axis=axis, origin=origin)
        targets = mirror_target_worlds(clones, mirror)
        for source_obj, clone in mirror_clone_pairs(clones):
            parent = mirror_parent_for(source_obj, clones, targets[clone])
            self._apply_clone_target(clone, parent, targets[clone], axis)
            update_scene_view_layer(self.scene)

    def _apply_clone_target(self, clone, parent, target_world, axis):
        if parent is None:
            _apply_world_target(clone, target_world, axis)
            return
        apply_parent_target(clone, parent, target_world)

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

    def _remap_external_refs(self):
        for clones in self.clones_by_sid.values():
            self._remap_cluster_refs(clones)

    def _remap_cluster_refs(self, clones):
        cluster_objs = set(clones.values())
        for ref in _cluster_refs(clones):
            self._remap_external_ref(ref, cluster_objs)

    def _remap_external_ref(self, ref, cluster_objs):
        if not _is_remappable_ref(ref, self.root.name, cluster_objs):
            return
        mirror = self._find_mirror_target(ref["value"])
        setattr(ref["owner"], ref["key"], mirror) if mirror else None
        self._queue_bind_restore(ref) if mirror else None
        trace_line(f"mirror remap owner={ref['clone_obj'].name} prop={ref['key']} src={ref['value'].name} mir={'' if mirror is None else mirror.name}") if mirror and _trace_match(ref["clone_obj"]) else None

    def _queue_bind_restore(self, ref):
        state = self._saved_bind_state(ref)
        self.pending_bind_refs.append((ref["clone_obj"], ref["owner"], state)) if state else None

    def _saved_bind_state(self, ref):
        sid = as_id(ref["clone_obj"].get("af_source_scp_id"))
        bid = as_id(ref["clone_obj"].get("af_source_bound_id"))
        key = _bind_state_key(bid, ref["owner"])
        return self.bind_state_by_sid.get(sid, {}).get(key)

    def _restore_pending_bind_states(self):
        if not self.pending_bind_refs:
            return
        update_scene_view_layer(self.scene)
        for clone_obj, owner, state in tuple(self.pending_bind_refs):
            trace_line(f"mirror bind owner={clone_obj.name} mod={owner.name}") if _restore_bind_state(owner, state) and _trace_match(clone_obj) else None
        self.pending_bind_refs.clear()
        update_scene_view_layer(self.scene)

    def _should_keep_existing(self, obj):
        sid = as_id(obj.get("af_source_scp_id"))
        ours = obj.get("af_scp_mirror") and obj.get("af_root_name") == self.root.name
        return bool(not ours or sid in self.desired_ids or (self.target_ids and sid not in self.affected_ids))

    def _find_mirror_target(self, obj):
        sid = as_id(obj.get("af_scp_id"))
        bid = as_id(obj.get("af_scp_bound_id"))
        return None if not sid or not bid else self._find_mirror_bound_obj(sid, bid)

    def _find_mirror_bound_obj(self, sid, bid):
        return next((obj for obj in self.scene.objects if self._is_mirror_bound_obj(obj, sid, bid)), None)

    def _is_mirror_bound_obj(self, obj, sid, bid):
        same_root = obj.get("af_root_name") == self.root.name
        same_scp = as_id(obj.get("af_source_scp_id")) == sid
        return bool(obj.get("af_scp_mirror") and same_root and same_scp and as_id(obj.get("af_source_bound_id")) == bid)


def sync_mirrors(sync, root, scene, scp_by_id, target_scp_ids=None):
    MirrorSceneSync(sync, root, scene, scp_by_id, target_scp_ids=target_scp_ids).run()
