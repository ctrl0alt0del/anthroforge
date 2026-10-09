"""Native surface propagation for muscle-parent fibers, without serial fallback."""
from mathutils import Vector
from ..scp_runtime.attachment_wave_capture import capture_attachment_wave, attachment_request_current
from ..vcp.attachment_wave_native import execute_attachment_wave
from ..vcp.runtime_state import set_fiber_invalid_reason, set_fiber_recompute_status
from .fiber_sync_helpers import mark_fiber_output_stale


def resolve_batch(root, scene, fibers):
    scps = {s.id: s for s in root.af_scp_system.scps}
    captured = capture_attachment_wave(root, scene, scps, (), (), fibers)
    result = execute_attachment_wave(captured.request)
    if not attachment_request_current(captured.request, root, scene): raise ValueError('Surface capture was superseded.')
    errors = dict(captured.fiber_issues); points = {}
    for identity, values, failed in zip(captured.request.fiber_ids, result.fiber_points, result.fiber_status):
        if failed: errors[identity] = 'Attachment surface changed or its binding is invalid. Use Rebind.'
        else: points[identity] = tuple(Vector(row) for row in values)
    return points, errors


def fail(root, scene, fiber, message):
    set_fiber_invalid_reason(fiber, message)
    set_fiber_recompute_status(fiber, 'INVALID_ATTACHMENT')
    mark_fiber_output_stale(scene, root.name, fiber.id)


def apply_batch(sync, root, scene, fibers):
    from ..scp_runtime.attachment_gate import attachments_enabled
    if not attachments_enabled(scene): return {f.id for f in fibers}
    try: points, errors = resolve_batch(root, scene, fibers)
    except (ValueError, RuntimeError, OSError) as exc:
        points, errors = {}, {f.id: str(exc) for f in fibers}
    from ..vcp.attachment_backend import attachment_runtime
    runtime = attachment_runtime(scene); sync.begin_point_batch()
    try: _apply_resolved(sync, root, scene, fibers, points, errors, runtime)
    finally: sync.end_point_batch()
    return {f.id for f in fibers}


def _apply_resolved(sync, root, scene, fibers, points, errors, runtime):
    for fiber in fibers:
        try:
            if fiber.id in errors: fail(root, scene, fiber, errors[fiber.id])
            elif fiber.id in points: _publish(sync, root, scene, fiber, points[fiber.id], runtime)
        except (ValueError, RuntimeError) as exc: fail(root, scene, fiber, str(exc))


def _publish(sync, root, scene, fiber, points, runtime):
    from ..vcp.free_path import is_free
    from ..vcp.fiber_support_validation import validate
    if not validate(root, scene, fiber, points, runtime): return _unsafe(root, scene, fiber)
    if is_free(fiber):
        from .free_fiber_runtime import validate_pair, publish
        validate_pair(fiber); publish(root, scene, fiber, points, validated=True)
    else: sync.apply_points(root, scene, fiber, points, commit=True)
    set_fiber_invalid_reason(fiber, '')


def _unsafe(root, scene, fiber):
    from ..vcp.free_path import is_free
    if is_free(fiber): return fail(root, scene, fiber, 'Parent deformation produced an unsafe route. Edit the Free path.')
    stamp = _reroute_stamp(root, scene, fiber)
    if fiber.get('af_parent_reroute_generation') == stamp: return
    fail(root, scene, fiber, 'Parent deformation produced an unsafe route; native rerouting is pending.')
    fiber['af_parent_reroute_generation'] = stamp
    from .fiber_refinement import request_fiber_refinement
    from ..vcp.fiber_authority import invalidate
    invalidate(fiber)
    request = request_fiber_refinement(root, scene, fiber, show_preview=False, quality='FINAL')
    if not request.ok: fail(root, scene, fiber, request.error)


def _reroute_stamp(root, scene, fiber):
    from hashlib import sha256
    from ..vcp.fiber_collision import CollisionOracle, _collider_stamp
    from ..vcp.attachment_surface import support_keys
    from ..utils import depsgraph_for_scene
    oracle = CollisionOracle(root, scene, depsgraph_for_scene(scene), supports=support_keys(fiber))
    rows = tuple((r['sid'], _collider_stamp(r['obj'])) for r in oracle.colliders())
    return sha256(repr((rows, fiber.a_attach_param, fiber.b_attach_param)).encode()).hexdigest()
