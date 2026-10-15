"""Short-lived UI bounds from exactly the geometry accepted by skin capture."""
import time
import numpy as np
from .capture import _candidate_objects, _evaluated_arrays, _role, _entity_id, _mirror_role, _include_fiber, _fiber_properties

_CACHE = {}


def model_length(root, context):
    key = root.as_pointer(); now = time.monotonic(); cached = _CACHE.get(key)
    if cached and now-cached[0] < .5:
        return cached[1]
    value = _measure(root, context.scene, context.evaluated_depsgraph_get())
    _CACHE[key] = now, value
    return value


def _measure(root, scene, depsgraph):
    bounds = []
    for obj in _candidate_objects(root, scene):
        arrays = _evaluated_arrays(obj, depsgraph)
        if arrays is not None:
            points = arrays[0]; bounds.append((obj, points.min(0), points.max(0)))
    muscles = {(_entity_id(obj, 'MUSCLE'), _mirror_role(obj)) for obj, _, _ in bounds if _role(obj) == 'MUSCLE'}
    fibers = _fiber_properties(root)
    bounds = [(low, high) for obj, low, high in bounds if _role(obj) != 'FIBER' or _include_fiber(obj, fibers, muscles)]
    return float(np.max(np.max([b[1] for b in bounds], axis=0)-np.min([b[0] for b in bounds], axis=0))) if bounds else 0.


def final_muscle(root, scene, identity):
    for obj in _candidate_objects(root, scene):
        if _role(obj) == 'MUSCLE' and _entity_id(obj, 'MUSCLE') == identity:
            if obj.type == 'MESH' and len(obj.data.polygons):
                return next((item for item in root.af_vcp_system.muscles if item.id == identity), None)
    return None
