"""Use the endpoint tools' evaluated-surface snapping and hard-anchor preflight.

Inputs and distances are world-space scene units. Valid hits include an `anchor`
record for publication and an `attachment` for native endpoint/touch RNA. The latter
contains the exact snapping payload; use it unchanged with zero touch offset.
`normal` follows authoring's outward convention; `native_normal` preserves the
native winding convention (different on reflected objects). Blocked/distant hits
expose the nearest location for review, but no attachment that can be published.
"""
from dataclasses import asdict
from mathutils import Vector
import numpy as np
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.geometry import world_vertices
from ...core.attachment_codec import fiber_surface_param
from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
from ...core.vcp import attachment_backend as backend
from ...core.vcp.fiber_anchor_preflight import FiberHardAnchor, evaluate_anchor_preflight
from ...core.vcp.v2.contracts import V2AnchorRole, V2ArrayColliderSnapshot, V2CollisionPolicy, V2Quality
from ...core.vcp.v2.scales import resolve_tolerances


def snap_points(root, scene, params, inventory):
    owner = params['instance_id']
    row = next((r for r in inventory['instances'] if r['instance_id'] == owner and r['has_surface']), None)
    require(row is not None, 'INSTANCE_NOT_FOUND', owner)
    obj = find_geometry_mesh_scp_obj(scene, root.name, owner)
    require(obj is not None, 'INSTANCE_NOT_FOUND', owner)
    runtime = backend.attachment_runtime(scene)
    topology = backend.surface_binding_topology(obj, runtime, scene)
    require(bool(topology), 'SURFACE_UNAVAILABLE', owner)
    hits = [snap_one(root, scene, obj, runtime, owner, point, i) for i, point in enumerate(params['points'])]
    preflight(hits, params, inventory)
    for hit in hits:
        validate_binding(hit, inventory['geometry'][owner])
        finalize(hit, params, topology, inventory['revision'])
    return hits


def snap_one(root, scene, obj, runtime, owner, guess, index):
    raw = backend.capture_attachment_from_world(root, scene, owner, Vector(guess), runtime)
    frame = backend.resolve_surface_frame(obj, raw, runtime, scene) if raw else None
    hit = dict(index=index, input_point=list(guess), owner=owner, hit=frame is not None, diagnostics=[])
    if frame is None:
        reject(hit, 'SURFACE_PICK_FAILED', 'No surface attachment could be resolved.')
        return hit
    point, native = frame['point_world'], frame['normal_world']
    sign = -1 if obj.evaluated_get(runtime['depsgraph']).matrix_world.to_3x3().determinant() < 0 else 1
    hit.update(point=list(point), normal=list(native * sign), native_normal=list(native), snap_distance=float(np.linalg.norm(np.asarray(point)-guess)))
    hit['attachment'] = native_attachment(root, scene, obj, raw)
    binding = {key: list(value) for key, value in fiber_surface_param(raw).items()}
    hit['anchor'] = dict(owner=owner, surface=list(point), point=list(point), normal=hit['normal'], offset=0., surface_binding=binding)
    return hit


def native_attachment(root, scene, obj, raw):
    parent_id = str(obj.get('af_scp_id', ''))
    require(find_geometry_mesh_scp_obj(scene, root.name, parent_id) == obj, 'NATIVE_ATTACHMENT_OWNER_UNRESOLVED', obj.name)
    return dict(parent_id=parent_id, attach_param=raw)


def preflight(hits, params, inventory):
    from .scene import mesh
    rows = tuple(FiberHardAnchor(tuple(h['point']), h['owner'], V2AnchorRole.TOUCH, h['index']) for h in hits if h['hit'])
    if not rows:
        return
    meshes = [mesh(row, inventory) for row in inventory['instances'] if row['has_surface']]
    colliders = tuple(V2ArrayColliderSnapshot(m.id, m.id, world_vertices(m), m.triangles) for m in meshes if len(m.triangles))
    radius = params.get('collision_radius', V2CollisionPolicy().collision_radius)
    slack = resolve_tolerances(colliders, radius, V2Quality.FINAL).clearance_slack
    result = evaluate_anchor_preflight(rows, colliders, {}, radius, slack, (inventory['revision'],))
    for violation in result.violations:
        hit = hits[violation.authored_index]
        reject(hit, 'ANCHOR_BLOCKED', f"Closest point is blocked by {violation.blocker_id}; choose another location on this SCP.")
        hit.setdefault('blockers', []).append(dict(asdict(violation), point=list(violation.point), role=violation.role.value))


def reject(hit, code, message):
    pointer = '/params/points/' + str(hit['index'])
    hit['diagnostics'].append(AuthoringError(code, message, pointer, (hit['owner'],)).diagnostic())


def validate_binding(hit, geometry):
    from .attachments import retained_binding
    if not hit['hit']:
        return
    try:
        retained_binding(geometry, hit['anchor'])
    except AuthoringError as error:
        reject(hit, error.code, str(error))


def finalize(hit, params, topology, revision):
    if hit['hit'] and hit['snap_distance'] > params.get('max_distance', float('inf')):
        reject(hit, 'SNAP_DISTANCE_EXCEEDED', 'Closest surface point exceeds max_distance.')
    hit.update(valid=not hit['diagnostics'], scene_revision=revision, topology_signature=topology)
    if not hit['valid']:
        hit.pop('anchor', None)
        hit.pop('attachment', None)
