"""Capture on Blender's thread, execute an owned snapshot, publish current results."""
from dataclasses import dataclass, replace
from ..warnings import session
from ..warnings.anchors import identity, publish
from ..warnings.coordinator import WakeAfter
from ..warnings.native_executor import NativeWarningExecutor
from . import warning_capture as capture

_EXECUTOR = None


@dataclass(frozen=True)
class CapturedFiber:
    reference: object
    signature: tuple
    anchors: tuple
    radius: float
    slack: float


def executor():
    global _EXECUTOR
    if _EXECUTOR is None: _EXECUTOR = NativeWarningExecutor()
    return _EXECUTOR


def reap():
    return _EXECUTOR is not None and _EXECUTOR.reap()


def close():
    global _EXECUTOR
    if _EXECUTOR is not None: _EXECUTOR.close()
    _EXECUTOR = None


def run(scene, root, selected, generation, valid):
    worker = executor()
    while worker.reap(): yield WakeAfter(0.016)
    depsgraph, runtime = capture.capture_root(scene, root)
    colliders, fibers = [], []
    yield from capture.capture_colliders(scene, root, depsgraph, colliders, runtime['geometry_objects'])
    yield from capture_fibers(scene, root, selected, generation, runtime, colliders, fibers)
    if not fibers: return
    pins = tuple((a.point, a.owner_id, max(0., f.radius-f.slack)) for f in fibers for a in f.anchors)
    token = session.measure('native_submit', worker.submit, colliders, pins)
    try:
        while worker.poll(token).state < 2: yield WakeAfter(0.016)
        yield from publish_results(scene, root, fibers, colliders, worker.read(token, colliders), generation, valid)
        worker.release(token)
    finally: worker.cancel(token)


def capture_fibers(scene, root, selected, generation, runtime, colliders, output):
    live = set()
    for fiber in root.af_vcp_system.fibers:
        ref, signature = identity(scene, root, fiber); live.add(ref.scope)
        if selected is None or str(fiber.id) in selected:
            session.REPOSITORY.state(ref.scope, 'CHECKING', generation)
            try:
                anchors = yield from capture_anchors(scene, root, fiber, runtime)
                slack = capture.preflight._clearance_slack(colliders, fiber.collision_radius, 'FINAL')
                output.append(CapturedFiber(ref, signature, anchors, float(fiber.collision_radius), slack))
            except (ValueError, RuntimeError, ReferenceError) as error:
                session.REPOSITORY.state(ref.scope, 'FAILED', generation, error)
                session.COORDINATOR.metrics['failures'] += 1
        yield
    remove_obsolete(scene, root, live)


def capture_anchors(scene, root, fiber, runtime):
    anchors = []
    for spec in capture.pin_specs(fiber):
        anchors.append(session.measure('pin_capture', capture.capture_pin, scene, root, runtime, spec))
        yield
    return tuple(anchors)


def remove_obsolete(scene, root, live):
    for scope in session.scopes_for(scene, root):
        if scope[3] == 'FIBER' and scope not in live: session.REPOSITORY.remove(scope)


def publish_results(scene, root, fibers, colliders, result, generation, valid):
    pairs, stats, elapsed = result
    session.COORDINATOR.metrics['native_worker_ms'] += elapsed
    grouped = {}
    for pair in pairs: grouped.setdefault(pair.edge, []).append(pair)
    offset, hierarchy = 0, capture.preflight._hierarchy(root)
    current = {str(f.id): f for f in root.af_vcp_system.fibers}
    for captured in fibers:
        rows = tuple(replace(p, edge=i) for i in range(len(captured.anchors)) for p in grouped.get(offset+i, ()))
        result = fiber_result(captured, colliders, hierarchy, rows, stats[offset:offset+len(captured.anchors)], generation)
        publish_current(scene, root, current.get(captured.reference.native_id), captured, result, generation, valid)
        offset += len(captured.anchors)
        yield


def fiber_result(fiber, colliders, hierarchy, pairs, stats, generation):
    violations = capture.preflight._violations(fiber.anchors, colliders, hierarchy, fiber.radius,
                                              max(0., fiber.radius-fiber.slack), pairs)
    return capture.preflight.FiberAnchorPreflightResult(not violations, violations,
        ('diagnostic', fiber.reference.scope, generation), sum(s.candidates for s in stats), sum(s.tested for s in stats), fiber.anchors)


def publish_current(scene, root, fiber, captured, result, generation, valid):
    if not valid(): return
    current = None if fiber is None else identity(scene, root, fiber)
    matches = current is not None and current[0].scope == captured.reference.scope and current[1] == captured.signature
    if matches and float(fiber.collision_radius) == captured.radius:
        publish(scene, root, fiber, result, generation)
        session.COORDINATOR.metrics['checked_entities'] += 1
        session.COORDINATOR.metrics['checked_pins'] += len(captured.anchors)
    else:
        session.COORDINATOR.metrics['stale_rejects'] += 1
        session.REPOSITORY.state(captured.reference.scope, 'PENDING', generation)
