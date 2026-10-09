"""Evaluated connectivity identities, independent of coordinate-based tessellation."""
import hashlib
import numpy as np
from ..utils import depsgraph_for_scene, scene_for_id


def signature(obj, runtime=None, scene=None):
    if obj is None: return ''
    cache = (runtime or {}).get('surface_cache', {})
    key = ('fiber_topology', obj.as_pointer())
    if key not in cache:
        depsgraph = (runtime or {}).get('depsgraph') or depsgraph_for_scene(scene or scene_for_id(obj))
        mesh = obj.evaluated_get(depsgraph).data
        digest = hashlib.sha256(str(len(mesh.vertices)).encode())
        for collection, field, width in ((mesh.edges, 'vertices', 2), (mesh.loops, 'vertex_index', 1), (mesh.polygons, 'loop_total', 1)):
            values = np.empty(len(collection) * width, dtype=np.int32)
            collection.foreach_get(field, values); digest.update(values.tobytes())
        cache[key] = 'connectivity-v1:' + digest.hexdigest()
    return cache[key]


def matches(obj, expected, runtime=None, scene=None):
    from .attachment_backend import surface_binding_topology
    capture = signature if str(expected).startswith('connectivity-v1:') else surface_binding_topology
    current = capture(obj, runtime, scene)
    return bool(current and (not expected or current == expected))
