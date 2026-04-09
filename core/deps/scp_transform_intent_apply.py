from mathutils import Matrix, Vector

from ..attachment_codec import parse_scp_attach_param, encode_scp_mesh_anchor, encode_surface_frame
from ..registry import SCPRegistry
from ..visualization.scp_sync_helpers import frame_basis3


def _get_scp_prop(root, scp_id):
    for scp in root.af_scp_system.scps:
        if scp.id == scp_id:
            return scp
    return None


def _props_by_id(root):
    return {scp.id: scp for scp in root.af_scp_system.scps}


def _local_matrix_from_prop(scp_prop):
    loc = Vector(scp_prop.local_origin)
    rot = scp_prop.local_rotation
    scale = scp_prop.local_scale
    return Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal((float(scale[0]), float(scale[1]), float(scale[2]), 1.0))


def _world_matrix_for_scp(scp_id, runtime_registry, props_by_id, cache):
    if scp_id in cache:
        return cache[scp_id]

    scp = runtime_registry.get(scp_id)
    scp_prop = props_by_id.get(scp_id)
    if scp is None or scp_prop is None:
        out = Matrix.Identity(4)
        cache[scp_id] = out
        return out

    if not scp_prop.parent_id:
        out = _local_matrix_from_prop(scp_prop)
        cache[scp_id] = out
        return out

    parent = runtime_registry.get(scp_prop.parent_id)
    if parent is None:
        out = _local_matrix_from_prop(scp_prop)
        cache[scp_id] = out
        return out

    parent_world = _world_matrix_for_scp(scp_prop.parent_id, runtime_registry, props_by_id, cache)
    mode, payload = parse_scp_attach_param(scp_prop.attach_param)

    if mode == "mesh_anchor":
        parent_local_point, child_local_point = payload
        anchor_world = parent_world @ parent_local_point
        rs = scp.local_rotation.to_4x4() @ Matrix.Diagonal((*scp.local_scale, 1.0))
        child_off = rs @ Vector((child_local_point.x, child_local_point.y, child_local_point.z, 1.0))
        obj_origin = anchor_world - Vector((child_off.x, child_off.y, child_off.z))
        out = Matrix.Translation(obj_origin) @ rs
        cache[scp_id] = out
        return out

    parent_param = payload.get("parent_param", 0.0)
    child_origin_local = payload.get("child_origin_local", Vector((0.0, 0.0, 0.0)))
    child_tangent_local = payload.get("child_tangent_local", Vector((1.0, 0.0, 0.0)))
    child_normal_local = payload.get("child_normal_local", Vector((0.0, 0.0, 1.0)))

    p_origin_local, p_tangent_local, p_normal_local = parent.shape.sample_attachment_frame_local(parent_param)
    parent_world3 = parent_world.to_3x3()
    p_origin_world = parent_world @ p_origin_local
    p_tangent_world = parent_world3 @ p_tangent_local
    p_normal_world = parent_world3 @ p_normal_local

    parent_basis = frame_basis3(p_tangent_world, p_normal_world)
    child_basis_local = frame_basis3(child_tangent_local, child_normal_local)
    attach_rot = parent_basis @ child_basis_local.inverted()
    final_rot = attach_rot @ scp.local_rotation

    sx = max(1e-9, float(scp.local_scale.x))
    sy = max(1e-9, float(scp.local_scale.y))
    sz = max(1e-9, float(scp.local_scale.z))
    child_off_world = final_rot @ (Matrix.Diagonal((sx, sy, sz)) @ child_origin_local)
    obj_origin = p_origin_world - child_off_world

    out = final_rot.to_4x4()
    out.translation = obj_origin
    cache[scp_id] = out
    return out


def _nearest_parent_param(parent_scp, parent_world, target_world):
    params = parent_scp.shape.get_attach_params() or [0.0]
    best_param = params[0]
    best_d2 = None
    for p in params:
        lp = parent_scp.shape.compute_local_point(p)
        wp = parent_world @ lp
        d2 = (wp - target_world).length_squared
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_param = p
    return best_param


def _set_root_from_world(scp_prop, matrix_world):
    loc, rot, scale = matrix_world.decompose()
    changed = False
    new_origin = (loc.x, loc.y, loc.z)
    new_rot = (rot.w, rot.x, rot.y, rot.z)
    new_scale = (scale.x, scale.y, scale.z)
    if tuple(scp_prop.local_origin) != new_origin:
        scp_prop.local_origin = new_origin
        changed = True
    if tuple(scp_prop.local_rotation) != new_rot:
        scp_prop.local_rotation = new_rot
        changed = True
    if tuple(scp_prop.local_scale) != new_scale:
        scp_prop.local_scale = new_scale
        changed = True
    return changed


def _set_parented_from_world(root, scp_prop, matrix_world):
    runtime = SCPRegistry(root)
    runtime.build()
    runtime_registry = runtime.registry
    props = _props_by_id(root)
    cache = {}

    child = runtime_registry.get(scp_prop.id)
    parent = runtime_registry.get(scp_prop.parent_id)
    if child is None or parent is None:
        return False

    parent_world = _world_matrix_for_scp(scp_prop.parent_id, runtime_registry, props, cache)
    obj_origin = matrix_world.to_translation()
    parent_param = _nearest_parent_param(parent, parent_world, obj_origin)
    mode, payload = parse_scp_attach_param(scp_prop.attach_param)

    if mode == "mesh_anchor":
        parent_local_point = parent.shape.compute_local_point(parent_param)
        anchor_world = parent_world @ parent_local_point
        rs = child.local_rotation.to_4x4() @ Matrix.Diagonal((*child.local_scale, 1.0))
        off4 = rs.inverted_safe() @ Vector((anchor_world.x - obj_origin.x, anchor_world.y - obj_origin.y, anchor_world.z - obj_origin.z, 1.0))
        child_local_point = Vector((off4.x, off4.y, off4.z))
        new_attach = encode_scp_mesh_anchor(parent_local_point, child_local_point)
    else:
        p_origin_local, p_tangent_local, p_normal_local = parent.shape.sample_attachment_frame_local(parent_param)
        pw3 = parent_world.to_3x3()
        p_origin_world = parent_world @ p_origin_local
        p_tangent_world = pw3 @ p_tangent_local
        p_normal_world = pw3 @ p_normal_local
        parent_basis = frame_basis3(p_tangent_world, p_normal_world)

        final_rot = matrix_world.to_3x3()
        child_basis_local = child.local_rotation @ final_rot.inverted() @ parent_basis
        child_tangent_local = child_basis_local @ Vector((1.0, 0.0, 0.0))
        child_normal_local = child_basis_local @ Vector((0.0, 0.0, 1.0))

        off_world = p_origin_world - obj_origin
        off_local_scaled = final_rot.inverted() @ off_world
        sx = max(1e-9, float(child.local_scale.x))
        sy = max(1e-9, float(child.local_scale.y))
        sz = max(1e-9, float(child.local_scale.z))
        child_origin_local = Vector((off_local_scaled.x / sx, off_local_scaled.y / sy, off_local_scaled.z / sz))

        new_attach = encode_surface_frame(
            parent_param=parent_param,
            child_origin_local=child_origin_local,
            child_tangent_local=child_tangent_local,
            child_normal_local=child_normal_local,
        )

    changed = False
    if (scp_prop.attach_param or "") != new_attach:
        scp_prop.attach_param = new_attach
        changed = True
    if tuple(scp_prop.local_origin) != (0.0, 0.0, 0.0):
        scp_prop.local_origin = (0.0, 0.0, 0.0)
        changed = True
    return changed


def apply_scp_transform_intent(root, scp_id, matrix_world):
    if root is None or not scp_id or matrix_world is None:
        return False
    scp_prop = _get_scp_prop(root, scp_id)
    if scp_prop is None:
        return False
    if not scp_prop.parent_id:
        return _set_root_from_world(scp_prop, matrix_world)
    return _set_parented_from_world(root, scp_prop, matrix_world)

