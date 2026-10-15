"""Scope instance selection while reusing the normal native volume evaluators."""
from contextlib import contextmanager
from contextvars import ContextVar
from .mirror_rules import mirror_matrix

_MIRROR = ContextVar('af_evaluated_mirror', default=None)


@contextmanager
def mirrored(rule):
    token = _MIRROR.set(rule)
    try: yield
    finally: _MIRROR.reset(token)


def active():
    return _MIRROR.get() is not None


def point(value):
    from mathutils import Vector
    rule = _MIRROR.get()
    return tuple(value) if rule is None else tuple(mirror_matrix(*rule) @ Vector(value))


def direction(value):
    from mathutils import Vector
    rule = _MIRROR.get()
    return Vector(value) if rule is None else mirror_matrix(*rule).to_3x3() @ Vector(value)


def domain(plane):
    if plane is None or not active(): return plane
    from mathutils import Vector
    normal = direction(plane['normal'])
    origin = Vector(point(Vector(plane['normal']) * plane['offset']))
    return dict(plane, normal=tuple(normal), offset=float(origin.dot(normal)))


def row(root, scene, fiber, original):
    if not active(): return original
    from .fiber_instance_runtime import actual_rows
    values = actual_rows(root, scene, fiber)
    return [point(p) for p in original] if values is None else values


def required(root, source, seen=()):
    from ..vcp.attachment_surface import muscle_backed
    if source is None or source.id in seen or getattr(source, 'use_mirrored_rows', False): return False
    fibers = {f.id: f for f in root.af_vcp_system.fibers}
    if any(muscle_backed(fibers[r.fiber_id]) for r in getattr(source, 'fiber_refs', ()) if r.fiber_id in fibers): return True
    surfaces = {s.id: s for s in root.af_vcp_system.fiber_surfaces}
    ids = [getattr(source, 'fiber_surface_id', ''), getattr(source, 'main_surface_id', '')]
    ids.extend(b.surface_id for b in getattr(source, 'branches', ()))
    return any(required(root, surfaces.get(key), (*seen, source.id)) for key in ids if key)
