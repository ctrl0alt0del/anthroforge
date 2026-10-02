"""Transient, immutable Muscle control observations; runtime owns the FIFO."""
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite

from .relationship_cache import runtime_identity

_EPOCH = 0
_RECORDS = {}
_BUSY = 0
_BORROWED = None
_CONTEXT_REVISION = 0


class ControlContextChanged(RuntimeError):
    pass


@dataclass(frozen=True)
class MuscleControlInput:
    epoch: int
    owners: tuple
    binding: tuple
    revision: int
    point: tuple
    muscle_id: str
    object_name: str


@dataclass
class ControlRecord:
    root: object
    scene: object
    control: object
    binding: tuple
    observed: tuple
    revision: int = 0
    handled: int = 0
    processing: int = 0
    failed: object = None


def reset_control_inputs():
    global _EPOCH, _BORROWED
    _RECORDS.clear()
    _EPOCH += 1
    _BORROWED = None


def input_key(value):
    return () if value is None else (value.epoch, value.owners, value.binding, value.revision)


def owners(root, scene, obj):
    return tuple(runtime_identity(value) for value in (scene, root, obj))


def control_binding(root, obj):
    from ..visualization.branch_control import control_part
    muscle = next((m for m in root.af_vcp_system.muscles if m.id == obj.get('af_muscle_id')), None)
    part = None if muscle is None else control_part(root, muscle, obj)
    if part is None or str(part.inflation_mode) != 'CTRL_POINT':
        return None
    return (str(muscle.id), str(muscle.surface_source_mode), str(muscle.fiber_surface_id),
            str(obj.get('af_muscle_branch_id', '')), str(obj.get('af_inflation_side', 'A')),
            str(part.inflation_mode), runtime_identity(part))


def _alive(record):
    try:
        return (record.scene.objects.get(record.control.name) == record.control
                and record.scene.objects.get(record.root.name) == record.root
                and control_binding(record.root, record.control) == record.binding)
    except (ReferenceError, AttributeError, TypeError):
        return False


def prune_inputs():
    for key, record in tuple(_RECORDS.items()):
        if not _alive(record):
            _RECORDS.pop(key, None)


def retire_control(obj):
    identity = runtime_identity(obj)
    for key in tuple(_RECORDS):
        if key[2] == identity:
            _RECORDS.pop(key, None)


def _coordinates(point):
    values = tuple(float(value) for value in point)
    if len(values) != 3 or not all(isfinite(value) for value in values):
        raise ValueError('Muscle control input must contain three finite coordinates')
    return values


def _record(root, scene, obj):
    key, binding = owners(root, scene, obj), control_binding(root, obj)
    if binding is None:
        retire_control(obj)
        return None
    record = _RECORDS.get(key)
    if record is None or record.binding != binding:
        stored = obj.get('af_muscle_ctrl_sync_location')
        record = ControlRecord(root, scene, obj, binding, None if stored is None else tuple(stored))
        _RECORDS[key] = record
    return record


def reserve_input(root, scene, obj, *, prune=True):
    if prune:
        prune_inputs()
    try:
        point = _coordinates(obj.location)
    except ReferenceError:
        return None
    obj = getattr(obj, "original", obj)
    return _reserve_record(_record(root, scene, obj), point)


def _reserve_record(record, point):
    # The caller has already checked the binding; no callbacks occur before this snapshot.
    if record is None or record.observed == point:
        return None
    record.observed = point
    record.revision += 1
    return MuscleControlInput(_EPOCH, owners(record.root, record.scene, record.control), record.binding,
                              record.revision, point, record.binding[0], str(record.control.name))


def input_record(value):
    if value is None or value.epoch != _EPOCH:
        return None
    record = _RECORDS.get(value.owners)
    if record is None or record.binding != value.binding:
        return None
    if not _alive(record):
        _RECORDS.pop(value.owners, None)
        return None
    return record


def claim_input(value):
    record = input_record(value)
    if record is None or record.processing or value.revision <= record.handled:
        return False
    record.processing = value.revision
    return True


def finish_input(value, success):
    record = input_record(value)
    if record is None:
        return
    record.processing = 0
    if success:
        record.handled = max(record.handled, value.revision)
        if record.failed and record.failed.revision <= record.handled:
            record.failed = None
    elif success is False and value.revision > record.handled:
        record.failed = value


def input_busy():
    return _BUSY > 0


@contextmanager
def acquisition_guard():
    global _BUSY
    _BUSY += 1
    try:
        yield
    finally:
        _BUSY -= 1


@contextmanager
def borrowed_graph(root, scene, graph):
    global _BORROWED
    previous = _BORROWED
    _BORROWED = (owners(root, scene, None)[:2], graph)
    try:
        yield
    finally:
        _BORROWED = previous


def acquire_graph(root, scene):
    global _BORROWED
    from ..utils import depsgraph_for_scene
    scope, _BORROWED = _BORROWED, None
    if scope is not None and scope[0] == owners(root, scene, None)[:2]:
        return scope[1]
    return depsgraph_for_scene(scene)


def dispatch_input(root, scene, value, deferred=False, fresh_context=False):
    from ..visualization.sync_runner import schedule_sync_from_dirty_hints, sync_from_dirty_hints
    if value is None:
        return False
    from ..visualization.sync_runner import runtime_request_active
    defer = fresh_context or (deferred and not runtime_request_active())
    dispatch = schedule_sync_from_dirty_hints if defer else sync_from_dirty_hints
    return dispatch(root=root, scene=scene, dirty_hints={}, full=False, source='depsgraph',
                    event_type='TRANSFORM', payload={'muscle_control_input': value})


def _observe_before_write(record):
    value = _reserve_record(record, _coordinates(record.control.location))
    if value is not None:
        dispatch_input(record.root, record.scene, value, deferred=input_busy())
    return value is None


def write_control(root, scene, obj, point, value=None):
    try:
        record = _record(root, scene, obj)
    except ReferenceError:
        return False
    if not _write_allowed(record, value):
        return False
    return _write_location(obj, point, record)


def _write_location(obj, point, record):
    from mathutils import Vector
    from ..visualization.muscle_sync_helpers import mark_inflation_ctrl_location
    revision = 0 if record is None else record.revision
    if record is not None:
        record.observed = tuple(Vector(point))
    obj.location = point
    if record is None or record.revision == revision:
        mark_inflation_ctrl_location(obj)
        if record is not None:
            record.observed = tuple(obj.location)
    return True


def _write_allowed(record, value):
    if record is None:
        return value is None
    if value is not None and not _input_matches(record, value):
        return False
    if not _alive(record):
        return False
    if record.observed is None and record.revision == 0:
        record.observed = tuple(record.control.location)
        return True
    if not _observe_before_write(record):
        return False
    revision = record.processing or record.handled if value is None else value.revision
    return record.revision <= revision


def _input_matches(record, value):
    return (value.epoch == _EPOCH and _RECORDS.get(value.owners) is record
            and record.binding == value.binding)


def freeze_payload(root, payload):
    from ..utils import scene_for_id
    if 'muscle_control_input' in payload:
        return payload
    scene = scene_for_id(root)
    obj = None if scene is None else scene.objects.get(payload.get('object_name', ''))
    value = None if obj is None else reserve_input(root, scene, obj)
    return dict(payload, muscle_control_input=value)


def retry_inputs(ctx):
    prune_inputs()
    failed = tuple(r.failed for r in _RECORDS.values() if r.failed and r.root == ctx.root
                   and r.scene == ctx.scene and r.failed.revision > r.handled and not r.processing)
    if not failed:
        return ()
    if ctx.is_full or (ctx.gate_meta or {}).get('source') == 'manual':
        return failed
    affected = _dependency_targets(ctx)
    return tuple(value for value in failed if ('MUSCLE', value.muscle_id) in affected)


def _dependency_targets(ctx):
    from .runtime_impact import dirty_start_nodes, source_start_nodes
    pending = list(source_start_nodes(dirty_start_nodes(ctx.dirty), ctx.gate_meta))
    seen = set()
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(ctx.adjacency.get(node, ()))
    return seen


def context_revision():
    return _CONTEXT_REVISION


def note_runtime_request(request):
    global _CONTEXT_REVISION
    if input_busy() and (request.full or any(request.dirty_hints.get(key) for key in ('SCP', 'FIBER', 'FIBER_SURFACE'))):
        _CONTEXT_REVISION += 1


def require_context(revision, base=None, generation=None):
    from ..utils import geometry_generation
    if revision != _CONTEXT_REVISION or (base is not None and geometry_generation(base) != generation):
        raise ControlContextChanged('Muscle snapping context changed during application')
