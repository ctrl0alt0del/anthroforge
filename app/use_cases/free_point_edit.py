"""Atomic incident-path updates for explicit native shared-point/graph edits."""
import copy
from ...core.vcp import free_path
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.vcp.shared_point_storage import point_users
from ...core.visualization import free_fiber_runtime as runtime
from ...adapters.free_fiber_transaction import run
from . import free_fiber as service


def capture(root, scene, fibers=None):
    values = root.af_vcp_system.fibers if fibers is None else fibers
    return {f.id: runtime.current(root, scene, f) for f in values if free_path.is_free(f)}


def _prepare(root, scene, fiber, previous):
    payload, points = previous; payload = copy.deepcopy(payload)
    anchors = runtime.structure(fiber)
    if len(anchors) != len(payload['structural']): raise ValueError('Free structural point count changed; edit its explicit path first.')
    for tag, (key, role) in zip(payload['structural'], anchors): tag.update(point_id=key, role=role)
    rows = free_path.adjust_anchors(points, free_path.tagged_indices(payload), runtime.anchor_points(root, scene, fiber), fiber.topology_mode == 'LOOP')
    payload['capture_revision'] = fiber.free_path_revision + 1
    raw, attachments = runtime.prepare(root, scene, fiber, payload, rows)
    return fiber, raw, attachments, rows


def apply_changed(root, scene, saved):
    fibers = {f.id: f for f in root.af_vcp_system.fibers}; prepared = []
    for key, previous in saved.items():
        fiber = fibers.get(key)
        if fiber is None or not free_path.is_free(fiber): continue
        payload = previous[0]
        if payload.get('bindings') == runtime.bindings(fiber) and tuple((r['point_id'], r['role']) for r in payload['structural']) == runtime.structure(fiber): continue
        prepared.append(_prepare(root, scene, fiber, previous))
    _publish(root, scene, prepared)
    ids = {row[0].id for row in prepared}
    if ids: service.rebuild(root, scene, ids)
    return ids


def _publish(root, scene, prepared):
    from ...core.visualization.free_output_validation import validate_outputs
    validate_outputs(root, scene, {f.id: rows for f, _raw, _a, rows in prepared},
                     {f.id: free_path.decode(raw) for f, raw, _a, _r in prepared})
    for fiber, raw, attachments, rows in prepared: service._store(root, scene, fiber, raw, attachments, rows)


def graph_action(root, scene, action):
    saved = capture(root, scene)
    def execute():
        value = action()
        apply_changed(root, scene, saved)
        return value
    return run(root, scene, execute) if saved else action()


def _restore_bindings(root, saved):
    points = {p.id: p for p in root.af_vcp_system.authored_points}
    with suppress_vcp_prop_updates():
        for payload, _values in saved.values():
            for tag, binding in zip(payload['structural'], payload['bindings']):
                point = points[tag['point_id']]
                for key, value in binding.items(): setattr(point, key, value)


def adjust(root, scene, fibers):
    saved = capture(root, scene, fibers)
    try: return run(root, scene, lambda: apply_changed(root, scene, saved))
    except Exception:
        _restore_bindings(root, saved)
        raise


def point_changed(point, context):
    fibers = [f for f, _i, _r in point_users(point.id_data, point.id) if free_path.is_free(f)]
    return adjust(point.id_data, context.scene, fibers) if fibers else set()
