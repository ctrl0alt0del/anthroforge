"""Resolve detached native attachment records without exposing RNA."""
from ...core.authoring.errors import require
from ...core.vcp.attachment_backend import resolve_attachment_world
from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
from ...core.attachment_codec import encode_fiber_surface_param, fiber_surface_param
from ...core.authoring.attachment_binding import capture as capture_binding
from .inventory import geometry_for
from ...core.authoring.attachment_binding import resolve as resolve_binding
import numpy as np


def native_owner(root, scene, owner):
    obj = find_geometry_mesh_scp_obj(scene, root.name, owner)
    require(obj is not None, 'NATIVE_ATTACHMENT_OWNER_UNRESOLVED', owner)
    identity = str(obj.get('af_scp_id', ''))
    require(find_geometry_mesh_scp_obj(scene, root.name, identity) == obj, 'NATIVE_ATTACHMENT_OWNER_UNRESOLVED', obj.name)
    return identity


def authoring_owner(root, scene, owner):
    obj = find_geometry_mesh_scp_obj(scene, root.name, owner)
    require(obj is not None, 'NATIVE_ATTACHMENT_OWNER_UNRESOLVED', owner)
    identity = 'AFI_' + obj['af_authoring_id'] if obj.get('af_authoring_id') else owner
    require(find_geometry_mesh_scp_obj(scene, root.name, identity) == obj, 'NATIVE_ATTACHMENT_OWNER_UNRESOLVED', obj.name)
    return identity


def snap_binding(root, scene, owner, point):
    from mathutils import Vector
    from ...core.vcp.attachment_backend import capture_attachment_from_world
    raw = capture_attachment_from_world(root, scene, owner, Vector(point))
    value = fiber_surface_param(raw) if raw else None
    require(value is not None, 'SURFACE_PICK_FAILED', owner)
    return {key: list(row) for key, row in value.items()}


def capture(root, scene, anchor):
    obj = find_geometry_mesh_scp_obj(scene, root.name, anchor['owner'])
    require(obj is not None, 'ATTACHMENT_CAPTURE_FAILED', anchor['owner'])
    geometry = geometry_for(obj)
    value = retained_binding(geometry, anchor) if anchor.get('surface_binding') else capture_binding(geometry, anchor['surface'], anchor['normal'])
    return encode_fiber_surface_param(value)


def retained_binding(geometry, anchor):
    value = anchor['surface_binding']
    point, normal = resolve_binding(geometry, value)
    require(np.linalg.norm(point-anchor['surface']) < 1e-5, 'ATTACHMENT_CAPTURE_FAILED')
    require(normal @ np.asarray(anchor['normal']) > 1-1e-6, 'ATTACHMENT_NORMAL_UNRESOLVED')
    return value


def normal_offset(root, scene, owner, offset):
    obj = find_geometry_mesh_scp_obj(scene, root.name, owner)
    require(obj is not None, 'NATIVE_ATTACHMENT_UNRESOLVED', owner)
    return offset * (-1 if obj.matrix_world.to_3x3().determinant() < 0 else 1)


def resolve_rows(root, scene, fiber):
    values, collections = fiber['values'], fiber['collections']
    if values['topology_mode'] == 'LOOP':
        rows = [r['values'] for r in collections['loop_anchors']]
    else:
        rows = [dict(parent_id=values['a_parent_id'], attach_param=values['a_attach_param'])]
        rows += [r['values'] for r in collections['mid_touches']]
        rows += [dict(parent_id=values['b_parent_id'], attach_param=values['b_attach_param'])]
    return [resolve(root, scene, row) for row in rows]


def resolve(root, scene, row):
    point = resolve_attachment_world(root, scene, row['parent_id'], row['attach_param'])
    require(point is not None, 'NATIVE_ATTACHMENT_UNRESOLVED')
    offset = normal_offset(root, scene, row['parent_id'], row.get('normal_offset', 0.))
    result = dict(owner=authoring_owner(root, scene, row['parent_id']), point=list(point), offset=offset)
    value = fiber_surface_param(row['attach_param'])
    if value:
        result['surface_binding'] = {k: list(v) for k, v in value.items()}
    return result
