"""Shared authored-pin snapping; node/Soft Tissue snapping remains unchanged.

A supplied runtime belongs to one immutable capture operation, not a persistent
edit session. Callers create a fresh runtime after any scene/attachment mutation.
"""
from dataclasses import replace
from time import perf_counter
from . import attachment_backend as backend
from .fiber_anchor_preflight import _capture_colliders
from .fiber_collision import CollisionOracle
from .fiber_pin_snap_search import FiberPinSnapResult, FiberPinSnapSearch, binding_row
from .fiber_pin_snap_validation import component_worlds
from .v2.contracts import V2Request, V2Settings, V2Quality, V2CollisionPolicy
from .v2.scales import resolve_tolerances


def snap_request(root, scene, runtime, radius):
    sources = CollisionOracle(root, scene, runtime['depsgraph'], radius, .002).colliders()
    colliders = _capture_colliders(sources)
    tolerances = resolve_tolerances(colliders, radius, V2Quality.FINAL)
    return V2Request(1, str(scene.as_pointer()), str(root.as_pointer()), 'pin-snap',
                     V2Settings(quality=V2Quality.FINAL), tolerances,
                     V2CollisionPolicy(collision_radius=radius), (), colliders)


def qualify_attachment(root, scene, owner, raw, runtime=None, radius=.002, offset=0., origin=None):
    started = perf_counter()
    runtime = runtime if runtime is not None else backend.attachment_runtime(scene)
    result = _qualify(root, scene, owner, raw, runtime, radius, offset, origin)
    result = replace(result, elapsed_ms=1000*(perf_counter()-started))
    runtime['pin_snap_last_result'] = result
    return result


def _qualify(root, scene, owner, raw, runtime, radius, offset, origin):
    obj = backend._parent_mesh(root, scene, owner)
    if obj is None or binding_row(obj, raw, runtime, offset) is None:
        return FiberPinSnapResult(reason='SURFACE_PICK_FAILED')
    try:
        request = _request(root, scene, runtime, radius)
        identity = str(obj.get('af_scp_id', '') or owner)
        result = FiberPinSnapSearch(request, obj, identity, raw, runtime, offset, _parts(runtime, request, identity), origin).run()
    except (OSError, RuntimeError) as error:
        result = FiberPinSnapResult(reason='BACKEND_UNAVAILABLE: ' + str(error))
    except ValueError as error:
        result = FiberPinSnapResult(reason='INVALID_CONFIGURATION: ' + str(error))
    return result


def _parts(runtime, request, owner):
    key = (request.scene_id, request.root_id, owner)
    cache = runtime.setdefault('pin_snap_parts', {})
    if key not in cache: cache[key] = component_worlds(request.colliders, owner)
    return cache[key]


def _request(root, scene, runtime, radius):
    key = (root.as_pointer(), scene.as_pointer(), float(radius))
    requests = runtime.setdefault('pin_snap_requests', {})
    if key not in requests: requests[key] = snap_request(root, scene, runtime, radius)
    return requests[key]


def capture_attachment_from_world(root, scene, parent_id, world_point, runtime=None, radius=.002, offset=0.):
    runtime = runtime if runtime is not None else backend.attachment_runtime(scene)
    raw = backend.capture_attachment_from_world(root, scene, parent_id, world_point, runtime)
    result = qualify_attachment(root, scene, parent_id, raw, runtime, radius, offset, world_point)
    return result.raw if result.valid else None


def capture_attachment_from_mesh_vertex(root, scene, parent_id, vertex_index, runtime=None, radius=.002, offset=0.):
    runtime = runtime if runtime is not None else backend.attachment_runtime(scene)
    raw = backend.capture_attachment_from_mesh_vertex(root, scene, parent_id, vertex_index, runtime)
    result = qualify_attachment(root, scene, parent_id, raw, runtime, radius, offset)
    return result.raw if result.valid else None


def capture_attachment_from_proxy_vertex(root, scene, parent_id, vertex_index, signature='', runtime=None, radius=.002, offset=0.):
    runtime = runtime if runtime is not None else backend.attachment_runtime(scene)
    raw = backend.capture_attachment_from_proxy_vertex(root, scene, parent_id, vertex_index, signature, runtime)
    result = qualify_attachment(root, scene, parent_id, raw, runtime, radius, offset)
    return result.raw if result.valid else None
