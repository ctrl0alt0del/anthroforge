from mathutils import Matrix, Vector

from ..utils import depsgraph_for_scene, scene_for_id, update_scene_view_layer
from .common import as_bool, as_id, as_vec3, find_geometry_mesh_scp_obj, find_transform_scp_obj, is_runtime_applied_matrix, mark_applied_matrix
from .common import vec3_close, is_matrix_close, matrix_flat16
from .child_anchor import anchor_mode as child_anchor_mode, capture_child_anchor
from .parent_anchor import anchor_mode as parent_anchor_mode, is_surface_binding, resolve_parent_frame, stored_parent_binding
from .runtime_state import attach_child_anchor_index, attach_child_normal_local, attach_child_origin_local, attach_child_tangent_local
from .runtime_state import attach_flow_param, attach_initialized, attach_parent_offset_local, attach_parent_tangent_hint_local
from .runtime_state import read_attachment_runtime, set_attach_child_anchor_index, set_attach_initialized, write_attachment_runtime
from .surface import basis_from_tangent_normal, build_face_centers, build_vertex_points, flow_hint_world, nearest_parent_param_from_world
from .surface import project_tangent_hint, resolve_tangent_strategy
from .tree import children_depth_order


def _child_basis_local(child_scp):
    tangent = as_vec3(attach_child_tangent_local(child_scp), (1.0, 0.0, 0.0))
    normal = as_vec3(attach_child_normal_local(child_scp), (0.0, 0.0, 1.0))
    return basis_from_tangent_normal(tangent, normal)[0]


def _new_surface_cache():
    return {}


def _resolved_tangent_strategy(child_scp, parent_obj):
    raw = getattr(child_scp, "attach_tangent_strategy", "AUTO")
    return resolve_tangent_strategy(parent_obj, raw)


def _stored_flow_param(child_scp):
    return attach_flow_param(child_scp)


def _stored_child_anchor_local(child_scp):
    return as_vec3(attach_child_origin_local(child_scp), (0.0, 0.0, 0.0))


def _child_anchor_index(child_scp):
    return attach_child_anchor_index(child_scp)


def _point_at(points, index):
    return None if points is None or index < 0 or index >= len(points) else points[index].copy()


def _child_anchor_points(child_scp, child_geometry_obj, depsgraph, surface_cache):
    mode = child_anchor_mode(child_scp)
    if child_geometry_obj is None or mode == "OBJECT_ORIGIN":
        return None
    builder = build_face_centers if mode == "FACE_CENTER" else build_vertex_points
    return builder(child_geometry_obj, depsgraph, cache=surface_cache)


def _nearest_point_index(points, target):
    best_index, best_d2 = -1, None
    for index, point in enumerate(points or ()):
        d2 = (Vector(point) - Vector(target)).length_squared
        best_index, best_d2 = (index, d2) if best_d2 is None or d2 < best_d2 else (best_index, best_d2)
    return best_index


def _resolved_child_anchor_index(child_scp, child_obj, points):
    index = _child_anchor_index(child_scp)
    if points is None or 0 <= index < len(points):
        return index
    index = _nearest_point_index(points, child_obj.matrix_world @ _stored_child_anchor_local(child_scp))
    set_attach_child_anchor_index(child_scp, index) if index >= 0 else None
    return index


# Capture reads the evaluated child geometry, but apply must consume the stored local anchor.
def _live_child_anchor_world(child_scp, child_obj, child_geometry_obj, depsgraph, surface_cache):
    if child_anchor_mode(child_scp) == "OBJECT_ORIGIN":
        return child_obj.matrix_world.to_translation().copy()
    points = _child_anchor_points(child_scp, child_geometry_obj, depsgraph, surface_cache)
    return _point_at(points, _resolved_child_anchor_index(child_scp, child_obj, points))


def _live_child_anchor_local(child_scp, child_obj, child_geometry_obj, depsgraph, surface_cache):
    anchor = _live_child_anchor_world(child_scp, child_obj, child_geometry_obj, depsgraph, surface_cache)
    return _stored_child_anchor_local(child_scp) if anchor is None else child_obj.matrix_world.inverted() @ anchor


def _applied_child_anchor_local(child_scp):
    return _stored_child_anchor_local(child_scp)


class AttachmentCapture:
    def __init__(self, child_scp, child_transform_obj, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, surface_cache=None):
        self.child_scp = child_scp
        self.child_transform_obj = child_transform_obj
        self.child_geometry_obj = child_geometry_obj
        self.parent_transform_obj = parent_transform_obj
        self.parent_geometry_obj = parent_geometry_obj
        self.depsgraph = depsgraph
        self.surface_cache = surface_cache or {}

    def run(self):
        candidate = capture_child_anchor(self.child_scp, self.child_geometry_obj, self.parent_transform_obj, self.parent_geometry_obj, self.depsgraph, origin_obj=self.child_transform_obj, surface_cache=self.surface_cache)
        if candidate is None:
            return False
        binding = dict(candidate.get("parent_binding", {}) or {})
        strategy = self._tangent_strategy()
        tangent_hint = self._parent_tangent_hint_local(binding)
        flow_param = self._parent_flow_param(binding, strategy, tangent_hint)
        frame = self._parent_frame(binding, strategy, tangent_hint, flow_param)
        if frame is None:
            return False
        child_frame = self._child_frame(candidate["child_anchor_world"], frame)
        offset = self._offset_local(candidate["child_anchor_world"], frame)
        return self._write_capture(binding, flow_param, candidate["child_anchor_index"], offset, tangent_hint, *child_frame)

    def _tangent_strategy(self):
        return _resolved_tangent_strategy(self.child_scp, self.parent_geometry_obj)

    def _parent_tangent_hint_local(self, binding):
        if not is_surface_binding(binding):
            return Vector((1.0, 0.0, 0.0))
        frame = self._parent_frame(binding, "STABLE_SURFACE", None, None)
        world_inv = self.parent_geometry_obj.matrix_world.to_quaternion().to_matrix().inverted()
        # Store the hint in rotation space so later parent scale cannot twist it.
        return world_inv @ frame["tangent_world"] if frame else Vector((1.0, 0.0, 0.0))

    def _parent_flow_param(self, binding, strategy, tangent_hint):
        if strategy != "DEFORMATION_FLOW" or not is_surface_binding(binding):
            return None
        frame = self._parent_frame(binding, "STABLE_SURFACE", tangent_hint, None)
        return None if frame is None else self._probe_flow_param(binding["param"], frame)

    def _parent_frame(self, binding, strategy, tangent_hint, flow_param):
        return resolve_parent_frame(binding, self.parent_transform_obj, self.parent_geometry_obj, self.depsgraph, self.surface_cache, tangent_hint=tangent_hint, tangent_strategy=strategy, flow_param=flow_param)

    def _probe_flow_param(self, parent_param, frame):
        # Flow mode tracks a second parent surface sample instead of a live triangle edge.
        tangent = project_tangent_hint(flow_hint_world(self.parent_geometry_obj), frame["normal_world"], frame["tangent_world"])
        point = frame["point_world"]
        for distance in self._probe_distances():
            param = nearest_parent_param_from_world(self.parent_geometry_obj, point + (tangent * distance), self.depsgraph, cache=self.surface_cache)
            if self._is_distinct_param(parent_param, param):
                return param
        return None

    def _probe_distances(self):
        size = max((float(value) for value in self.parent_geometry_obj.dimensions), default=1.0)
        return tuple(size * factor for factor in (0.02, 0.05, 0.1))

    def _is_distinct_param(self, parent_param, flow_param):
        if flow_param is None:
            return False
        same_tri = tuple(flow_param["tri_vidx"]) == tuple(parent_param["tri_vidx"])
        return not (same_tri and vec3_close(flow_param["tri_weights"], parent_param["tri_weights"], eps=1.0e-4))

    def _offset_local(self, child_anchor_world, frame):
        return frame["basis_world"].inverted() @ (child_anchor_world - frame["point_world"])

    def _child_frame(self, child_anchor_world, frame):
        origin = self.child_transform_obj.matrix_world.inverted() @ child_anchor_world
        rotation_inv = self.child_transform_obj.matrix_world.to_quaternion().to_matrix().inverted()
        tangent = rotation_inv @ frame["tangent_world"]
        normal = rotation_inv @ frame["normal_world"]
        return origin, tangent, normal

    def _write_capture(self, binding, flow_param, child_anchor_index, parent_offset, parent_tangent, child_origin, child_tangent, child_normal):
        changed = False
        changed |= self._write_parent_binding(binding)
        changed |= self._write_vec("attach_parent_offset_local", parent_offset)
        changed |= self._write_vec("attach_parent_tangent_hint_local", parent_tangent)
        changed |= self._write_flow(flow_param)
        changed |= self._write_scalar("attach_child_anchor_index", int(child_anchor_index))
        changed |= self._write_vec("attach_child_origin_local", child_origin)
        changed |= self._write_vec("attach_child_tangent_local", child_tangent)
        changed |= self._write_vec("attach_child_normal_local", child_normal)
        return self._mark_initialized() or changed

    def _write_parent_binding(self, binding):
        if not is_surface_binding(binding):
            return self._clear_parent_surface_binding()
        param = dict((binding or {}).get("param", {}) or {})
        tri = tuple(int(v) for v in param.get("tri_vidx", (-1, -1, -1)))
        weights = tuple(float(v) for v in param.get("tri_weights", (1.0, 0.0, 0.0)))
        changed = self._write_field("attach_parent_tri_vidx", tri)
        return self._write_field("attach_parent_tri_weights", weights, eps=1.0e-7) or changed

    def _clear_parent_surface_binding(self):
        changed = self._write_field("attach_parent_tri_vidx", (-1, -1, -1))
        return self._write_field("attach_parent_tri_weights", (1.0, 0.0, 0.0), eps=1.0e-7) or changed

    def _write_flow(self, param):
        tri = (-1, -1, -1) if param is None else tuple(int(v) for v in param["tri_vidx"])
        weights = (1.0, 0.0, 0.0) if param is None else tuple(float(v) for v in param["tri_weights"])
        changed = self._write_field("attach_parent_flow_tri_vidx", tri)
        return self._write_field("attach_parent_flow_tri_weights", weights, eps=1.0e-7) or changed

    def _write_field(self, key, value, eps=None):
        current = read_attachment_runtime(self.child_scp, key)
        same = vec3_close(current, value, eps=eps) if eps is not None else tuple(current) == tuple(value)
        if same:
            return False
        write_attachment_runtime(self.child_scp, key, value)
        return True

    def _write_scalar(self, key, value):
        if read_attachment_runtime(self.child_scp, key) == value:
            return False
        write_attachment_runtime(self.child_scp, key, value)
        return True

    def _write_vec(self, key, value):
        current = as_vec3(read_attachment_runtime(self.child_scp, key), (0.0, 0.0, 0.0))
        if (current - value).length <= 1.0e-7:
            return False
        write_attachment_runtime(self.child_scp, key, (float(value.x), float(value.y), float(value.z)))
        return True

    def _mark_initialized(self):
        if attach_initialized(self.child_scp):
            return False
        set_attach_initialized(self.child_scp, True)
        return True


def capture_attachment_from_link(child_scp, child_transform_obj, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph=None):
    depsgraph = depsgraph or depsgraph_for_scene(_attachment_scene(child_transform_obj, child_geometry_obj, parent_transform_obj, parent_geometry_obj))
    if depsgraph is None:
        return False
    return AttachmentCapture(child_scp, child_transform_obj, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, _new_surface_cache()).run()


def recapture_attachment_for_scp(root, scene, sid):
    depsgraph = depsgraph_for_scene(scene)
    if depsgraph is None:
        return False
    scp_by_id = {as_id(s.id): s for s in root.af_scp_system.scps}
    return _authoring_capture_one(scp_by_id, scene, root.name, sid, depsgraph, _new_surface_cache())


def capture_authored_scp_attachments(root, scene, target_scp_ids=None):
    depsgraph = depsgraph_for_scene(scene)
    if root is None or depsgraph is None:
        return set()
    scp_by_id = {as_id(s.id): s for s in root.af_scp_system.scps}
    wanted = _authoring_attachment_ids(scp_by_id, target_scp_ids)
    cache = _new_surface_cache()
    return {sid for sid in sorted(wanted) if _authoring_capture_one(scp_by_id, scene, root.name, sid, depsgraph, cache)}


def _authoring_attachment_ids(scp_by_id, target_scp_ids):
    ids = {sid for sid, scp in scp_by_id.items() if as_id(getattr(scp, "parent_id", ""))}
    targets = {as_id(v) for v in set(target_scp_ids or ()) if as_id(v)}
    return ids if not targets else ids & targets


class AttachmentApply:
    def __init__(self, child_scp, child_obj, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, surface_cache=None):
        self.child_scp = child_scp
        self.child_obj = child_obj
        self.child_geometry_obj = child_geometry_obj
        self.parent_transform_obj = parent_transform_obj
        self.parent_geometry_obj = parent_geometry_obj
        self.depsgraph = depsgraph
        self.surface_cache = surface_cache or {}

    def run(self):
        frame = self._parent_frame(self._tangent_strategy())
        if frame is None:
            return False
        matrix_world = self._matrix_world(frame)
        if is_matrix_close(matrix_flat16(self.child_obj.matrix_world), matrix_flat16(matrix_world), eps=1.0e-7):
            return False
        self.child_obj.matrix_world = matrix_world
        mark_applied_matrix(self.child_obj)
        return True

    def _tangent_strategy(self):
        return _resolved_tangent_strategy(self.child_scp, self.parent_geometry_obj)

    def _parent_frame(self, strategy):
        binding = stored_parent_binding(self.child_scp)
        return resolve_parent_frame(binding, self.parent_transform_obj, self.parent_geometry_obj, self.depsgraph, self.surface_cache, tangent_hint=self._parent_tangent_hint(), tangent_strategy=strategy, flow_param=_stored_flow_param(self.child_scp))

    def _parent_tangent_hint(self):
        return as_vec3(attach_parent_tangent_hint_local(self.child_scp), (1.0, 0.0, 0.0))

    def _matrix_world(self, frame):
        follow = as_bool(getattr(self.child_scp, "attach_follow_rotation", True), default=True)
        rotation = self._rotation_world(frame, follow)
        anchor = _applied_child_anchor_local(self.child_scp)
        position = frame["point_world"] + self._parent_offset_world(frame) - (rotation @ self._scaled_child_anchor(anchor))
        return self._compose_matrix(position, rotation, follow)

    def _parent_offset_world(self, frame):
        offset = as_vec3(attach_parent_offset_local(self.child_scp), (0.0, 0.0, 0.0))
        return frame["basis_world"] @ offset

    def _rotation_world(self, frame, follow_rotation):
        if not follow_rotation:
            return self.child_obj.matrix_world.to_quaternion().to_matrix()
        return (frame["basis_world"] @ _child_basis_local(self.child_scp).inverted()).normalized()

    def _scaled_child_anchor(self, origin):
        scale = self.child_obj.matrix_world.to_scale()
        return Vector((float(origin.x) * float(scale.x), float(origin.y) * float(scale.y), float(origin.z) * float(scale.z)))

    def _compose_matrix(self, position, rotation, follow_rotation):
        if follow_rotation:
            return Matrix.LocRotScale(position, rotation.to_quaternion(), self.child_obj.matrix_world.to_scale())
        matrix_world = self.child_obj.matrix_world.copy()
        matrix_world.translation = position
        return matrix_world


def capture_dirty_scp_attachments(root, scene, dirty_scp_ids, source="", recapture_ids=None, apply_parent_ids=None):
    source = as_id(source).lower()
    if not _capture_source_allows(source):
        return set()
    direct_ids = _direct_capture_ids(dirty_scp_ids, recapture_ids)
    if not direct_ids:
        return set()
    depsgraph = depsgraph_for_scene(scene)
    if depsgraph is None:
        return set()
    surface_cache = _new_surface_cache()
    scp_by_id = {as_id(s.id): s for s in root.af_scp_system.scps}
    direct_ids = _allowed_direct_ids(source, scp_by_id, direct_ids, apply_parent_ids)
    return {sid for sid in sorted(direct_ids) if _capture_one(scp_by_id, scene, root.name, sid, depsgraph, surface_cache)}


def _capture_source_allows(source):
    return str(source or "").lower() in {"depsgraph", "shortcut"}


def _direct_capture_ids(dirty_scp_ids, recapture_ids):
    dirty_ids = {as_id(value) for value in set(dirty_scp_ids or set()) if as_id(value)}
    direct_ids = {as_id(value) for value in set(recapture_ids or set()) if as_id(value)}
    return dirty_ids & direct_ids


def _blocked_capture_ids(scp_by_id, direct_ids, apply_parent_ids):
    parent_ids = {as_id(value) for value in set(apply_parent_ids or set()) if as_id(value)}
    return {sid for sid in set(direct_ids or set()) if as_id(getattr(scp_by_id.get(sid), "parent_id", "")) in parent_ids}


def _allowed_direct_ids(source, scp_by_id, direct_ids, apply_parent_ids):
    if str(source or "").lower() == "shortcut":
        return set(direct_ids or set())
    return set(direct_ids or set()) - _blocked_capture_ids(scp_by_id, direct_ids, apply_parent_ids)


def _needs_child_geometry(child_scp):
    return child_anchor_mode(child_scp) != "OBJECT_ORIGIN"


def _needs_parent_geometry(child_scp):
    return parent_anchor_mode(child_scp) == "SURFACE_NEAREST"


def _has_parent_frame_source(parent_transform, parent_geometry):
    return parent_transform is not None or parent_geometry is not None


def _missing_attachment_objects(child_scp, child_transform, child_geometry, parent_transform, parent_geometry):
    if child_scp is None or child_transform is None or not _has_parent_frame_source(parent_transform, parent_geometry):
        return True
    if _needs_child_geometry(child_scp) and child_geometry is None:
        return True
    return _needs_parent_geometry(child_scp) and parent_geometry is None


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
    parent_transform = find_transform_scp_obj(scene, root_name, parent_id)
    parent_geometry = find_geometry_mesh_scp_obj(scene, root_name, parent_id)
    if child_scp is None or not parent_id:
        return None
    if _missing_attachment_objects(child_scp, child_transform, child_geometry, parent_transform, parent_geometry):
        return None
    return child_scp, child_transform, child_geometry, parent_transform, parent_geometry


def _run_capture(args, depsgraph, surface_cache):
    if args is None:
        return False
    return AttachmentCapture(*args, depsgraph, surface_cache).run()


def _attachment_scene(*objs):
    for obj in objs:
        scene = scene_for_id(obj)
        if scene is not None:
            return scene
    return None


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
        _refresh_child_chain(scene, active_parent_ids, sid, surface_cache)
    return {sid} if changed else set()


def _refresh_child_chain(scene, active_parent_ids, sid, surface_cache):
    active_parent_ids.add(sid)
    update_scene_view_layer(scene)
    surface_cache.clear()


def _apply_child_runtime(root, scene, sid, child_scp, parent_id, surface_cache):
    child_obj = find_transform_scp_obj(scene, root.name, sid)
    child_geometry = find_geometry_mesh_scp_obj(scene, root.name, sid)
    parent_transform = find_transform_scp_obj(scene, root.name, parent_id)
    parent_geometry = find_geometry_mesh_scp_obj(scene, root.name, parent_id)
    depsgraph = depsgraph_for_scene(scene)
    if depsgraph is None:
        return False
    if not _is_initialized(child_scp):
        return False
    if _missing_attachment_objects(child_scp, child_obj, child_geometry, parent_transform, parent_geometry):
        return False
    return AttachmentApply(child_scp, child_obj, child_geometry, parent_transform, parent_geometry, depsgraph, surface_cache).run()


def _is_initialized(child_scp):
    return as_bool(attach_initialized(child_scp), default=False)
