"""One-shot native tightening of exact sampled spans, retaining every hard pin."""
from dataclasses import replace
import numpy as np
from ..v2.contracts import V2Anchor, V2Settings
from .production import begin_v3
from .native_controller import solve_native_controller
from .solver import _validate_live
from types import SimpleNamespace
from ..v2.collision import cached_native_collision_world_batch


def tighten(request, points, pins, owners, *, accepted_steps=1, max_displacement=None, cyclic=False):
    points = np.asarray(points, dtype=np.float64); pins = tuple(pins); owners = tuple(owners)
    validate_input(points, pins, owners, accepted_steps, max_displacement, cyclic)
    if not valid_path(request, points, pins, owners, cyclic): raise ValueError('TIGHTENING_UNSAFE_SEED')
    output = points.copy(); reports = []
    for index, indices in enumerate(span_indices(len(points), pins, cyclic)):
        pair = owners[index], owners[(index + 1) % len(owners)]
        values, report = solve_span(request, points[indices], pair, accepted_steps, max_displacement)
        output[indices] = values; reports.append(report)
    validate_result(points, output, pins, max_displacement, cyclic)
    if not valid_path(request, output, pins, owners, cyclic): raise ValueError('TIGHTENING_UNSAFE_RESULT')
    return output, dict(metrics(points, output, cyclic), spans=reports, validated=True)


def validate_input(points, pins, owners, steps, limit, cyclic):
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError('TIGHTENING_INVALID_POINTS')
    if len(pins) != len(owners) or len(pins) < (3 if cyclic else 2): raise ValueError('TIGHTENING_INVALID_PINS')
    if any(not isinstance(i, (int, np.integer)) for i in pins) or tuple(sorted(set(pins))) != pins:
        raise ValueError('TIGHTENING_INVALID_PINS')
    if pins[0] != 0 or pins[-1] >= len(points) or (not cyclic and pins[-1] != len(points)-1):
        raise ValueError('TIGHTENING_INVALID_PINS')
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 64:
        raise ValueError('TIGHTENING_INVALID_STEPS')
    if limit is not None and (not np.isfinite(limit) or limit <= 0): raise ValueError('TIGHTENING_INVALID_LIMIT')
    if np.any(lengths(points, cyclic) <= 1e-12): raise ValueError('TIGHTENING_DEGENERATE_SEED')


def span_indices(count, pins, cyclic):
    ends = (*pins[1:], count) if cyclic else pins[1:]
    return [np.arange(a, b+1) % count for a, b in zip(pins, ends)]


def valid_path(request, points, pins, owners, cyclic):
    anchors = tuple(V2Anchor(tuple(points[i]), owner) for i, owner in zip(pins, owners))
    probe = SimpleNamespace(request=replace(request, anchors=anchors), pins=pins, cyclic=cyclic,
                            world=cached_native_collision_world_batch(request.colliders))
    return _validate_live(probe, points)


def span_request(request, points, owners, steps):
    anchors = (V2Anchor(tuple(points[0]), owners[0], 'ENDPOINT_A', 0),
               V2Anchor(tuple(points[-1]), owners[1], 'ENDPOINT_B', 1))
    settings = V2Settings(quality='FINAL', node_count=len(points), max_accepted_steps=steps,
                          length_weight=request.settings.length_weight)
    return replace(request, settings=settings, anchors=anchors, warm_seed=tuple(map(tuple, points)))


def solve_span(request, points, owners, steps, limit):
    session = begin_v3(span_request(request, points, owners, steps), use_planner=False,
                       native_session=True, native_controller=True)
    try:
        package, native = solve_native_controller(session, max_step_displacement=None if limit is None else limit/steps)
        if not package.result.validated: raise ValueError('TIGHTENING_UNSAFE_RESULT: ' + package.result.message)
        output = np.asarray(package.result.points, dtype=np.float64)
        validate_result(points, output, (0, len(points)-1), limit, False)
        return output, dict(termination=package.result.termination.value, accepted_steps=sum(s.accepted for s in native.spans),
                            rejected_steps=sum(s.rejected for s in native.spans), elapsed_ms=native.elapsed_ms,
                            solver_version=package.result.engine_version, backend_version=package.result.backend_version)
    finally:
        session.cancel()


def lengths(points, cyclic):
    return np.linalg.norm(np.diff(np.vstack((points, points[0])) if cyclic else points, axis=0), axis=1)


def metrics(before, after, cyclic=False):
    initial, final = float(lengths(before, cyclic).sum()), float(lengths(after, cyclic).sum())
    delta = np.linalg.norm(after-before, axis=1)
    return dict(length_before=initial, length_after=final, length_reduction=initial-final,
                length_reduction_fraction=(initial-final)/initial, max_displacement=float(delta.max()),
                rms_displacement=float(np.sqrt(np.mean(delta*delta))))


def validate_result(before, after, pins, limit, cyclic):
    if before.shape != after.shape or not np.isfinite(after).all(): raise ValueError('TIGHTENING_INVALID_RESULT')
    if not np.array_equal(before[list(pins)], after[list(pins)]): raise ValueError('TIGHTENING_PIN_MOVED')
    result = metrics(before, after, cyclic); tolerance = 1e-10*max(1., result['length_before'])
    if limit is not None and result['max_displacement'] > limit+tolerance: raise ValueError('TIGHTENING_LIMIT_EXCEEDED')
    if result['length_reduction'] < -tolerance: raise ValueError('TIGHTENING_LENGTH_INCREASED')
    if np.any(lengths(after, cyclic) <= 1e-12): raise ValueError('TIGHTENING_DEGENERATE_RESULT')
