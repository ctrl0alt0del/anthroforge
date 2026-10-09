"""Validate retained paths with the same native clearance policy as Fiber V3."""
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
from mathutils import Vector
from .attachment_backend import attachment_runtime
from .attachment_surface import support_keys
from .fiber_modes import is_loop_fiber
from .fiber_node_attachment import _anchor_specs, _pin_indices
from .fiber_pin_snapping import _request
from .v2.contracts import V2Anchor
from .v2.collision import cached_native_collision_world
from .v3.solver import _validate_live


def validate(root, scene, fiber, points, runtime=None):
    points = tuple(Vector(p) for p in points)
    runtime = attachment_runtime(scene) if runtime is None else runtime; runtime['supports'] = support_keys(fiber)
    specs = _anchor_specs(root, scene, fiber, runtime)
    from .shared_point_storage import slots
    if len(specs) != len(slots(fiber)): raise ValueError('A mandatory structural binding does not resolve.')
    anchors = tuple(V2Anchor(tuple(row[2]), row[0]) for row in specs)
    request = replace(_request(root, scene, runtime, fiber.collision_radius), anchors=anchors)
    cyclic = is_loop_fiber(fiber); values = np.asarray(points, dtype=np.float64)
    pins = _structural_indices(fiber, points, specs, cyclic)
    if len(pins) != len(specs) or any((points[i] - row[2]).length > 1e-5 for i, row in zip(pins, specs)):
        raise ValueError('Structural anchors do not match their retained bindings.')
    probe = SimpleNamespace(request=request, pins=pins, cyclic=cyclic,
                            world=cached_native_collision_world(request.colliders))
    return _validate_live(probe, values)


def _structural_indices(fiber, points, specs, cyclic):
    from .free_path import is_free, decode, tagged_indices
    return tagged_indices(decode(fiber.free_path_json)) if is_free(fiber) else _pin_indices(points, [r[2] for r in specs], cyclic)


def require_safe(root, scene, fiber, points):
    from .attachment_surface import muscle_backed
    if muscle_backed(fiber) and not validate(root, scene, fiber, points):
        raise ValueError('Fiber route collides with a selected support or SCP. Edit the Free path or reroute the Controlled fiber.')
