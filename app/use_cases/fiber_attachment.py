"""Transactional surface assignment shared by UI and authoring commands."""
from ...core.vcp.surface_reference import key, from_object
from ...core.vcp.attachment_surface import support_keys, resolve_object
from ...core.vcp.attachment_backend import attachment_runtime, resolve_attachment_world
from ...core.vcp.fiber_pin_snapping import capture_attachment_from_world, qualify_attachment
from ...core.vcp.shared_point_storage import point_users
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.deps.surface_dependencies import require_acyclic
from ...adapters.free_fiber_transaction import run
from . import free_point_edit


def selected_target(root, obj):
    if obj is None or obj.get('af_root_name') != root.name: raise ValueError('Select an attachment surface in this avatar.')
    target = key(from_object(obj))
    if not target: raise ValueError('Select SCP geometry or a published Muscle surface.')
    return target


def assign(root, scene, point, target, position=None, raw=None):
    target = key(target); users = tuple(f for f, _, _ in point_users(root, point.id))
    runtime = attachment_runtime(scene)
    runtime['supports'] = _proposed_supports(users, point.id, target)
    radius = max((f.collision_radius for f in users), default=.002)
    raw = _qualified(root, scene, target, position, raw, runtime, radius, point.normal_offset)
    saved = _capture_edit(root, scene, users)
    return run(root, scene, lambda: _assign(root, scene, point, target, raw, users, saved))


def _qualified(root, scene, target, position, raw, runtime, radius, offset):
    if raw is None:
        if position is None: raise ValueError('Assign/Rebind requires a surface position.')
        raw = capture_attachment_from_world(root, scene, target, position, runtime, radius, offset)
    if raw is None: raise ValueError('No qualified surface binding at this position.')
    for value in (0., offset):
        result = qualify_attachment(root, scene, target, raw, runtime, radius, value)
        if not result.valid or result.raw != raw: raise ValueError('The selected binding is not collision-clear.')
    return raw


def _proposed_supports(fibers, point_id, target):
    from ...core.vcp.shared_point_storage import slots, point_record
    values = [row.target_id for f in fibers for row in f.attachment_supports]
    values.extend(target if p.id == point_id else p.parent_id for f in fibers
                  for owner, slot, _role in slots(f) if (p := point_record(owner, slot)) is not None)
    return tuple(dict.fromkeys(values))


def _capture_edit(root, scene, fibers):
    from ...core.vcp.free_path import is_free
    return {f.id: _edit_path(root, scene, f) for f in fibers if is_free(f)}


def _edit_path(root, scene, fiber):
    from ...core.visualization import free_fiber_runtime as runtime
    from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
    try: return runtime.current(root, scene, fiber)
    except ValueError:
        payload = runtime.validate_pair(fiber)
        points = persisted_fiber_points(scene, root.name, fiber.id)
        if points is None or len(points) != len(payload['samples']): raise ValueError('No retained path for explicit Rebind.')
        return payload, points


def rebind_fiber(root, scene, fiber):
    from ...core.vcp.shared_point_storage import slots, point_record
    records = tuple(dict((p.id, p) for owner, slot, _ in slots(fiber) if (p := point_record(owner, slot))).values())
    users = tuple({f.id: f for p in records for f, _, _ in point_users(root, p.id)}.values())
    saved = _capture_edit(root, scene, users)
    positions = _retained_positions(root, scene, fiber)
    runtime = attachment_runtime(scene); runtime['supports'] = tuple(dict.fromkeys(k for f in users for k in support_keys(f)))
    radius = max(f.collision_radius for f in users)
    bindings = [(p, _qualified(root, scene, p.parent_id, positions[p.id], None, runtime, radius, p.normal_offset)) for p in records]
    return run(root, scene, lambda: _rebind_all(root, scene, users, saved, bindings))


def _retained_positions(root, scene, fiber):
    from ...core.vcp import free_path
    from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
    from ...core.vcp.fiber_node_attachment_codec import decode_node_attachments
    points = persisted_fiber_points(scene, root.name, fiber.id)
    if not points: raise ValueError('No retained geometry for Rebind.')
    if free_path.is_free(fiber):
        payload = free_path.decode(fiber.free_path_json)
        return {tag['point_id']: points[i] for tag, i in zip(payload['structural'], free_path.tagged_indices(payload))}
    from ...core.vcp.shared_point_storage import slots, point_record
    payload = decode_node_attachments(fiber.node_attachments_json)
    records = [point_record(owner, slot) for owner, slot, _ in slots(fiber)]
    return _controlled_positions(payload, records, points)


def _controlled_positions(payload, records, points):
    result = {}
    for point in records:
        matches = [i for i, node in enumerate(payload.nodes if payload else ())
                   if node.target_id == point.parent_id and node.attach_raw == point.attach_param]
        if len(matches) != 1: raise ValueError('No unique retained structural station; assign the point explicitly.')
        result[point.id] = points[matches[0]]
    return result


def set_symmetry(root, scene, fiber, mode, axis='X', origin=(0., 0., 0.)):
    if mode not in {'INHERIT', 'NONE', 'EXPLICIT'} or axis not in {'X', 'Y', 'Z'}: raise ValueError('Invalid symmetry setting.')
    return run(root, scene, lambda: _symmetry(root, scene, fiber, mode, axis, origin))


def _symmetry(root, scene, fiber, mode, axis, origin):
    from ...core.visualization.attachment_mirror_rules import for_fiber
    from ...core.visualization.sync_runner import sync_from_dirty_hints
    if mode == 'INHERIT': fiber.pop('af_authoring_symmetry', None)
    else: fiber['af_authoring_symmetry'] = 'explicit' if mode == 'NONE' else 'native_mirror'
    fiber['af_authoring_mirror_axis'] = axis; fiber['af_authoring_mirror_origin'] = list(origin)
    for_fiber(fiber, {s.id: s for s in root.af_scp_system.scps})
    sync_from_dirty_hints(root, scene, {'FIBER': {fiber.id}}, source='symmetry', event_type='UPDATE')


def _rebind_all(root, scene, users, saved, bindings):
    with suppress_vcp_prop_updates():
        for point, raw in bindings: point.attach_param = raw
    require_acyclic(root); free_point_edit.apply_changed(root, scene, saved)
    _refresh(root, scene, [f for f in users if f.behavior_mode != 'FREE'])
    return tuple(f.id for f in users)


def _assign(root, scene, point, target, raw, users, saved):
    with suppress_vcp_prop_updates(): point.parent_id, point.attach_param = target, raw
    require_acyclic(root)
    free_point_edit.apply_changed(root, scene, saved)
    _refresh(root, scene, [f for f in users if f.behavior_mode != 'FREE'])
    return point.id


def rebind(root, scene, point, position=None):
    if position is None:
        position = resolve_attachment_world(root, scene, point.parent_id, point.attach_param)
    if position is None: raise ValueError('Binding is invalid. Select a new surface position for Rebind.')
    return assign(root, scene, point, point.parent_id, position)


def set_supports(root, scene, fiber, targets):
    targets = tuple(dict.fromkeys(key(value) for value in targets))
    if any(not value or resolve_object(root, scene, value) is None for value in targets):
        raise ValueError('A selected support surface is unavailable.')
    return run(root, scene, lambda: _set_supports(root, scene, fiber, targets))


def _set_supports(root, scene, fiber, targets):
    from ...core.vcp.free_path import is_free
    from ...core.visualization.free_fiber_runtime import current
    previous = current(root, scene, fiber) if is_free(fiber) else None
    with suppress_vcp_prop_updates():
        fiber.attachment_supports.clear()
        for target in targets: fiber.attachment_supports.add().target_id = target
    require_acyclic(root)
    if previous:
        from .free_fiber import commit
        commit(root, scene, fiber, *previous, fiber.free_path_revision)
    else: _refresh(root, scene, (fiber,))
    return fiber.id


def _refresh(root, scene, fibers):
    from ...core.vcp.fiber_node_attachment import clear_fiber_node_attachments
    from ...core.visualization.fiber_sync_helpers import mark_fiber_output_stale
    from ...core.visualization.fiber_refinement import request_fiber_refinement
    from ...core.vcp.fiber_authority import invalidate
    for fiber in fibers:
        invalidate(fiber); clear_fiber_node_attachments(fiber)
        mark_fiber_output_stale(scene, root.name, fiber.id)
        result = request_fiber_refinement(root, scene, fiber, show_preview=False, quality='FINAL')
        if not result.ok: raise ValueError(result.error)
