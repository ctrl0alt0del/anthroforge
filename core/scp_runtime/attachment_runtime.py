import bpy
from mathutils import Matrix, Vector

from .common import as_bool, as_id, as_vec3, find_geometry_mesh_scp_obj, find_transform_scp_obj, is_runtime_applied_matrix, mark_applied_matrix
from .common import set_prop_raw, vec3_close, is_matrix_close, matrix_flat16
from .child_anchor import capture_child_anchor
from .surface import basis_from_tangent_normal, frame_from_parent_param
from .tree import children_depth_order


def _child_basis_local(child_scp):
    tangent = as_vec3(getattr(child_scp, "attach_child_tangent_local", (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))
    normal = as_vec3(getattr(child_scp, "attach_child_normal_local", (0.0, 0.0, 1.0)), (0.0, 0.0, 1.0))
    return basis_from_tangent_normal(tangent, normal)[0]


def _new_surface_cache():
    return {}


class AttachmentCapture:
    def __init__(self, child_scp, child_transform_obj, child_geometry_obj, parent_geometry_obj, depsgraph, surface_cache=None):
        self.child_scp = child_scp
        self.child_transform_obj = child_transform_obj
        self.child_geometry_obj = child_geometry_obj
        self.parent_geometry_obj = parent_geometry_obj
        self.depsgraph = depsgraph
        self.surface_cache = surface_cache or {}

    def run(self):
        candidate = capture_child_anchor(self.child_scp, self.child_geometry_obj, self.parent_geometry_obj, self.depsgraph, origin_obj=self.child_transform_obj, surface_cache=self.surface_cache)
        if candidate is None:
            return False
        tangent_hint = self._parent_tangent_hint_local(candidate["parent_param"])
        frame = frame_from_parent_param(self.parent_geometry_obj, candidate["parent_param"], self.depsgraph, cache=self.surface_cache, tangent_hint=tangent_hint)
        if frame is None:
            return False
        child_frame = self._child_frame(candidate["child_anchor_world"], frame)
        return self._write_capture(candidate["parent_param"], self._offset_local(candidate["child_anchor_world"], frame), tangent_hint, *child_frame)

    def _parent_tangent_hint_local(self, parent_param):
        frame = frame_from_parent_param(self.parent_geometry_obj, parent_param, self.depsgraph, cache=self.surface_cache)
        world_inv = self.parent_geometry_obj.matrix_world.to_quaternion().to_matrix().inverted()
        # Store the hint in rotation space so later parent scale cannot twist it.
        return world_inv @ frame["tangent_world"] if frame else Vector((1.0, 0.0, 0.0))

    def _offset_local(self, child_anchor_world, frame):
        return frame["basis_world"].inverted() @ (child_anchor_world - frame["point_world"])

    def _child_frame(self, child_anchor_world, frame):
        origin = self.child_transform_obj.matrix_world.inverted() @ child_anchor_world
        rotation_inv = self.child_transform_obj.matrix_world.to_quaternion().to_matrix().inverted()
        tangent = rotation_inv @ frame["tangent_world"]
        normal = rotation_inv @ frame["normal_world"]
        return origin, tangent, normal

    def _write_capture(self, param, parent_offset, parent_tangent, child_origin, child_tangent, child_normal):
        changed = False
        changed |= self._write_field("attach_parent_tri_vidx", tuple(int(v) for v in param["tri_vidx"]))
        changed |= self._write_field("attach_parent_tri_weights", tuple(float(v) for v in param["tri_weights"]), eps=1.0e-7)
        changed |= self._write_vec("attach_parent_offset_local", parent_offset)
        changed |= self._write_vec("attach_parent_tangent_hint_local", parent_tangent)
        changed |= self._write_vec("attach_child_origin_local", child_origin)
        changed |= self._write_vec("attach_child_tangent_local", child_tangent)
        changed |= self._write_vec("attach_child_normal_local", child_normal)
        return self._mark_initialized() or changed

    def _write_field(self, key, value, eps=None):
        current = getattr(self.child_scp, key, None)
        same = vec3_close(current, value, eps=eps) if eps is not None else tuple(current) == tuple(value)
        if same:
            return False
        set_prop_raw(self.child_scp, key, value)
        return True

    def _write_vec(self, key, value):
        current = as_vec3(getattr(self.child_scp, key, (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
        if (current - value).length <= 1.0e-7:
            return False
        set_prop_raw(self.child_scp, key, (float(value.x), float(value.y), float(value.z)))
        return True

    def _mark_initialized(self):
        if as_bool(getattr(self.child_scp, "attach_initialized", False), default=False):
            return False
        set_prop_raw(self.child_scp, "attach_initialized", True)
        return True


def capture_attachment_from_link(child_scp, child_transform_obj, child_geometry_obj, parent_geometry_obj, depsgraph=None):
    depsgraph = depsgraph or bpy.context.evaluated_depsgraph_get()
    return AttachmentCapture(child_scp, child_transform_obj, child_geometry_obj, parent_geometry_obj, depsgraph, _new_surface_cache()).run()


def recapture_attachment_for_scp(root, scene, sid):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scp_by_id = {as_id(s.id): s for s in root.af_scp_system.scps}
    return _authoring_capture_one(scp_by_id, scene, root.name, sid, depsgraph, _new_surface_cache())


class AttachmentApply:
    def __init__(self, child_scp, child_obj, parent_geometry_obj, depsgraph, surface_cache=None):
        self.child_scp = child_scp
        self.child_obj = child_obj
        self.parent_geometry_obj = parent_geometry_obj
        self.depsgraph = depsgraph
        self.surface_cache = surface_cache or {}

    def run(self):
        frame = frame_from_parent_param(self.parent_geometry_obj, self._parent_param(), self.depsgraph, cache=self.surface_cache, tangent_hint=self._parent_tangent_hint())
        if frame is None:
            return False
        matrix_world = self._matrix_world(frame)
        if is_matrix_close(matrix_flat16(self.child_obj.matrix_world), matrix_flat16(matrix_world), eps=1.0e-7):
            return False
        self.child_obj.matrix_world = matrix_world
        mark_applied_matrix(self.child_obj)
        return True

    def _parent_param(self):
        return {
            "tri_vidx": tuple(int(v) for v in getattr(self.child_scp, "attach_parent_tri_vidx", (-1, -1, -1))),
            "tri_weights": tuple(float(v) for v in getattr(self.child_scp, "attach_parent_tri_weights", (1.0, 0.0, 0.0))),
        }

    def _parent_tangent_hint(self):
        return as_vec3(getattr(self.child_scp, "attach_parent_tangent_hint_local", (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))

    def _matrix_world(self, frame):
        follow = as_bool(getattr(self.child_scp, "attach_follow_rotation", True), default=True)
        rotation = self._rotation_world(frame, follow)
        position = frame["point_world"] + self._parent_offset_world(frame) - (rotation @ self._scaled_child_anchor())
        return self._compose_matrix(position, rotation, follow)

    def _parent_offset_world(self, frame):
        offset = as_vec3(getattr(self.child_scp, "attach_parent_offset_local", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
        return frame["basis_world"] @ offset

    def _rotation_world(self, frame, follow_rotation):
        if not follow_rotation:
            return self.child_obj.matrix_world.to_quaternion().to_matrix()
        return (frame["basis_world"] @ _child_basis_local(self.child_scp).inverted()).normalized()

    def _scaled_child_anchor(self):
        origin = as_vec3(getattr(self.child_scp, "attach_child_origin_local", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
        scale = self.child_obj.matrix_world.to_scale()
        return Vector((float(origin.x) * float(scale.x), float(origin.y) * float(scale.y), float(origin.z) * float(scale.z)))

    def _compose_matrix(self, position, rotation, follow_rotation):
        if follow_rotation:
            return Matrix.LocRotScale(position, rotation.to_quaternion(), self.child_obj.matrix_world.to_scale())
        matrix_world = self.child_obj.matrix_world.copy()
        matrix_world.translation = position
        return matrix_world


def capture_dirty_scp_attachments(root, scene, dirty_scp_ids, source="", recapture_ids=None, apply_parent_ids=None):
    if as_id(source).lower() != "depsgraph":
        return set()
    direct_ids = _direct_capture_ids(dirty_scp_ids, recapture_ids)
    if not direct_ids:
        return set()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    surface_cache = _new_surface_cache()
    scp_by_id = {as_id(s.id): s for s in root.af_scp_system.scps}
    direct_ids -= _blocked_capture_ids(scp_by_id, direct_ids, apply_parent_ids)
    return {sid for sid in sorted(direct_ids) if _capture_one(scp_by_id, scene, root.name, sid, depsgraph, surface_cache)}


def _direct_capture_ids(dirty_scp_ids, recapture_ids):
    dirty_ids = {as_id(value) for value in set(dirty_scp_ids or set()) if as_id(value)}
    direct_ids = {as_id(value) for value in set(recapture_ids or set()) if as_id(value)}
    return dirty_ids & direct_ids


def _blocked_capture_ids(scp_by_id, direct_ids, apply_parent_ids):
    parent_ids = {as_id(value) for value in set(apply_parent_ids or set()) if as_id(value)}
    return {sid for sid in set(direct_ids or set()) if as_id(getattr(scp_by_id.get(sid), "parent_id", "")) in parent_ids}


def _capture_one(scp_by_id, scene, root_name, sid, depsgraph, surface_cache):
    args = _capture_args(scp_by_id, scene, root_name, sid)
    if args is None or is_runtime_applied_matrix(args[1]):
        return False
    return _run_capture(args, depsgraph, surface_cache)


def _authoring_capture_one(scp_by_id, scene, root_name, sid, depsgraph, surface_cache):
    return _run_capture(_capture_args(scp_by_id, scene, root_name, sid), depsgraph, surface_cache)


def _capture_args(scp_by_id, scene, root_name, sid):
    child_scp = scp_by_id.get(sid)
    parent_id = as_id(getattr(child_scp, "parent_id", ""))
    child_transform = find_transform_scp_obj(scene, root_name, sid)
    child_geometry = find_geometry_mesh_scp_obj(scene, root_name, sid)
    parent_geometry = find_geometry_mesh_scp_obj(scene, root_name, parent_id)
    if child_scp is None or not parent_id or child_transform is None or child_geometry is None or parent_geometry is None:
        return None
    return child_scp, child_transform, child_geometry, parent_geometry


def _run_capture(args, depsgraph, surface_cache):
    if args is None:
        return False
    return AttachmentCapture(*args, depsgraph, surface_cache).run()


def apply_scp_attachments(sync, root, scene, scp_by_id, target_scp_ids=None, parent_ids=None, gate_meta=None):
    _ = sync
    _ = gate_meta
    active_parent_ids = {as_id(v) for v in set(parent_ids or set()) if as_id(v)}
    if not active_parent_ids:
        return set()
    return _apply_attachment_targets(root, scene, scp_by_id, target_scp_ids, active_parent_ids)


def _apply_attachment_targets(root, scene, scp_by_id, target_scp_ids, active_parent_ids):
    surface_cache = _new_surface_cache()
    changed = set()
    targets = None if target_scp_ids is None else {as_id(v) for v in set(target_scp_ids)}
    for sid in children_depth_order(scp_by_id):
        changed |= _apply_child(root, scene, scp_by_id, sid, targets, active_parent_ids, surface_cache)
    return changed


def _apply_child(root, scene, scp_by_id, sid, targets, active_parent_ids, surface_cache):
    child_scp = scp_by_id.get(sid)
    parent_id = as_id(getattr(child_scp, "parent_id", ""))
    _ = targets
    if child_scp is None or parent_id not in active_parent_ids:
        return set()
    changed = _apply_child_runtime(root, scene, sid, child_scp, parent_id, surface_cache)
    if changed:
        _refresh_child_chain(active_parent_ids, sid, surface_cache)
    return {sid} if changed else set()


def _refresh_child_chain(active_parent_ids, sid, surface_cache):
    active_parent_ids.add(sid)
    bpy.context.view_layer.update()
    surface_cache.clear()


def _apply_child_runtime(root, scene, sid, child_scp, parent_id, surface_cache):
    child_obj = find_transform_scp_obj(scene, root.name, sid)
    parent_obj = find_geometry_mesh_scp_obj(scene, root.name, parent_id)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if child_obj is None or parent_obj is None or not _is_initialized(child_scp):
        return False
    return AttachmentApply(child_scp, child_obj, parent_obj, depsgraph, surface_cache).run()


def _is_initialized(child_scp):
    return as_bool(getattr(child_scp, "attach_initialized", False), default=False)
