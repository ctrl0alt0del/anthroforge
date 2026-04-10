from mathutils import Matrix, Vector

from ..attachment_codec import parse_scp_attach_descriptor
from ..registry import SCPRegistry
from .transform_behaviors import (
    compose_attachment_world_matrix,
    update_attachment_from_world,
)


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
    mode, payload, behavior = parse_scp_attach_descriptor(scp_prop.attach_param)
    out = compose_attachment_world_matrix(
        child_scp=scp,
        parent_scp=parent,
        parent_world=parent_world,
        mode=mode,
        payload=payload,
        behavior=behavior,
    )
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
    mode, payload, behavior = parse_scp_attach_descriptor(scp_prop.attach_param)
    new_attach = update_attachment_from_world(
        child_scp=child,
        parent_scp=parent,
        parent_world=parent_world,
        mode=mode,
        current_payload=payload,
        behavior=behavior,
        target_matrix_world=matrix_world,
        nearest_parent_param_fn=_nearest_parent_param,
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
