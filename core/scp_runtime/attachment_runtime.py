import bpy
from mathutils import Matrix, Vector

from .common import as_bool, as_id, as_vec3, find_source_scp_obj, is_runtime_applied_matrix, mark_applied_matrix
from .common import set_prop_raw, vec3_close, is_matrix_close, matrix_flat16
from .surface import basis_from_tangent_normal, frame_from_parent_param, nearest_parent_param_from_world, nearest_world_point_on_surface
from .tree import children_depth_order


def _child_basis_local(child_scp):
    tangent = as_vec3(getattr(child_scp, "attach_child_tangent_local", (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0))
    normal = as_vec3(getattr(child_scp, "attach_child_normal_local", (0.0, 0.0, 1.0)), (0.0, 0.0, 1.0))
    return basis_from_tangent_normal(tangent, normal)[0]


class AttachmentCapture:
    def __init__(self, child_scp, child_obj, parent_obj, depsgraph):
        self.child_scp = child_scp
        self.child_obj = child_obj
        self.parent_obj = parent_obj
        self.depsgraph = depsgraph

    def run(self):
        param = nearest_parent_param_from_world(self.parent_obj, self._target_world(), self.depsgraph)
        frame = None if param is None else frame_from_parent_param(self.parent_obj, param, self.depsgraph)
        if frame is None:
            return False
        child_frame = self._child_frame(frame)
        return self._write_capture(param, *child_frame)

    def _target_world(self):
        if as_bool(getattr(self.child_scp, "attach_initialized", False), default=False):
            origin_local = as_vec3(getattr(self.child_scp, "attach_child_origin_local", (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
            return self.child_obj.matrix_world @ origin_local
        return self.child_obj.matrix_world.translation.copy()

    def _child_frame(self, frame):
        anchor_world = nearest_world_point_on_surface(self.child_obj, frame["point_world"], self.depsgraph)
        anchor_world = frame["point_world"].copy() if anchor_world is None else anchor_world
        origin = self.child_obj.matrix_world.inverted() @ anchor_world
        rotation_inv = self.child_obj.matrix_world.to_quaternion().to_matrix().inverted()
        tangent = rotation_inv @ frame["tangent_world"]
        normal = rotation_inv @ frame["normal_world"]
        return origin, tangent, normal

    def _write_capture(self, param, child_origin, child_tangent, child_normal):
        changed = False
        changed |= self._write_field("attach_parent_tri_vidx", tuple(int(v) for v in param["tri_vidx"]))
        changed |= self._write_field("attach_parent_tri_weights", tuple(float(v) for v in param["tri_weights"]), eps=1.0e-7)
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


class AttachmentApply:
    def __init__(self, child_scp, child_obj, parent_obj, depsgraph):
        self.child_scp = child_scp
        self.child_obj = child_obj
        self.parent_obj = parent_obj
        self.depsgraph = depsgraph

    def run(self):
        frame = frame_from_parent_param(self.parent_obj, self._parent_param(), self.depsgraph)
        if frame is None:
            return False
        matrix_world = self._matrix_world(frame)
        if is_matrix_close(matrix_flat16(self.child_obj.matrix_world), matrix_flat16(matrix_world), eps=1.0e-7):
            return False
        self.child_obj.matrix_world = matrix_world
        mark_applied_matrix(self.child_obj)
        return True

    def _parent_param(self):
        return {"tri_vidx": tuple(int(v) for v in getattr(self.child_scp, "attach_parent_tri_vidx", (-1, -1, -1))), "tri_weights": tuple(float(v) for v in getattr(self.child_scp, "attach_parent_tri_weights", (1.0, 0.0, 0.0)))}

    def _matrix_world(self, frame):
        follow = as_bool(getattr(self.child_scp, "attach_follow_rotation", True), default=True)
        rotation = self._rotation_world(frame, follow)
        position = frame["point_world"] - (rotation @ self._scaled_child_anchor())
        return self._compose_matrix(position, rotation, follow)

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


def capture_dirty_scp_attachments(root, scene, dirty_scp_ids, source="", event_type=""):
    if as_id(source).lower() != "depsgraph" or as_id(event_type).upper() != "TRANSFORM":
        return set()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scp_by_id = {as_id(s.id): s for s in root.af_scp_system.scps}
    return {sid for sid in sorted({as_id(v) for v in set(dirty_scp_ids or set())}) if _capture_one(scp_by_id, scene, root.name, sid, depsgraph)}


def _capture_one(scp_by_id, scene, root_name, sid, depsgraph):
    child_scp = scp_by_id.get(sid)
    parent_id = as_id(getattr(child_scp, "parent_id", ""))
    child_obj = find_source_scp_obj(scene, root_name, sid)
    parent_obj = find_source_scp_obj(scene, root_name, parent_id)
    if child_scp is None or not parent_id or child_obj is None or parent_obj is None:
        return False
    if is_runtime_applied_matrix(child_obj):
        return False
    return AttachmentCapture(child_scp, child_obj, parent_obj, depsgraph).run()


def apply_scp_attachments(sync, root, scene, scp_by_id, target_scp_ids=None, source_parent_ids=None, gate_meta=None):
    _ = sync
    _ = gate_meta
    parent_ids = {as_id(v) for v in set(source_parent_ids or set()) if as_id(v)}
    if not parent_ids:
        return set()
    return _apply_attachment_targets(root, scene, scp_by_id, target_scp_ids, parent_ids)


def _apply_attachment_targets(root, scene, scp_by_id, target_scp_ids, active_parent_ids):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    changed = set()
    targets = None if target_scp_ids is None else {as_id(v) for v in set(target_scp_ids)}
    for sid in children_depth_order(scp_by_id):
        changed |= _apply_child(root, scene, scp_by_id, sid, targets, active_parent_ids, depsgraph)
    return changed


def _apply_child(root, scene, scp_by_id, sid, targets, active_parent_ids, depsgraph):
    child_scp = scp_by_id.get(sid)
    parent_id = as_id(getattr(child_scp, "parent_id", ""))
    if child_scp is None or parent_id not in active_parent_ids or not _allowed_target(sid, parent_id, targets):
        return set()
    changed = _apply_child_runtime(root, scene, sid, child_scp, parent_id, depsgraph)
    if changed:
        active_parent_ids.add(sid)
    return {sid} if changed else set()


def _allowed_target(sid, parent_id, targets):
    return targets is None or sid in targets or parent_id in targets


def _apply_child_runtime(root, scene, sid, child_scp, parent_id, depsgraph):
    child_obj = find_source_scp_obj(scene, root.name, sid)
    parent_obj = find_source_scp_obj(scene, root.name, parent_id)
    if child_obj is None or parent_obj is None:
        return False
    _ensure_capture(child_scp, child_obj, parent_obj, depsgraph)
    return AttachmentApply(child_scp, child_obj, parent_obj, depsgraph).run()


def _ensure_capture(child_scp, child_obj, parent_obj, depsgraph):
    if as_bool(getattr(child_scp, "attach_initialized", False), default=False):
        return
    AttachmentCapture(child_scp, child_obj, parent_obj, depsgraph).run()
