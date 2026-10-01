"""Compare evaluated attachment inputs, independently of Blender's dirty flags.

Keep only fingerprints and matrices, scoped to the original scene/view layer,
root and object. No evaluated RNA references survive a dependency-graph pass.
"""
from array import array
from collections import OrderedDict
import hashlib

import bpy
from bpy.app.handlers import persistent

from ..utils import view_layer_for_scene

_STATES = OrderedDict()
_MAX_STATES = 8192
_EVENTS = ('load_pre', 'undo_pre', 'undo_post', 'redo_pre', 'redo_post')


def _identity(value):
    original = getattr(value, 'original', value)
    return 0 if original is None else int(getattr(original, 'session_uid', 0) or original.as_pointer())


def _key(root, obj, depsgraph):
    return (_identity(depsgraph.scene), _identity(depsgraph.view_layer), _identity(root), _identity(obj))


def _remember(key, state):
    if state is None:
        _STATES.pop(key, None); return
    _STATES[key] = state; _STATES.move_to_end(key)
    while len(_STATES) > _MAX_STATES: _STATES.popitem(last=False)


def observe_scp_state(root, obj, depsgraph):
    """Return actual (transform, geometry) changes; unreadable inputs stay dirty."""
    key = _key(root, obj, depsgraph); previous = _STATES.get(key)
    state = _snapshot(obj, depsgraph); _remember(key, state)
    if previous is None or state is None: return True, True
    return previous[:2] != state[:2], previous != state


def _snapshot(obj, depsgraph):
    try:
        original = obj.original; evaluated = original.evaluated_get(depsgraph)
        roles = (str(original.get('af_scp_id', '')), bool(original.get('af_scp_transform')), bool(original.get('af_scp_geometry')))
        matrix = tuple(float(value) for row in evaluated.matrix_world for value in row)
        geometry = (_identity(original.data), _geometry_digest(evaluated)) if roles[2] else None
        return roles, matrix, geometry
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _geometry_digest(evaluated):
    if evaluated.type == 'MESH': return _mesh_digest(evaluated.data)
    mesh = evaluated.to_mesh()
    try:
        if mesh is None: raise ValueError('No evaluated attachment mesh')
        return _mesh_digest(mesh)
    finally: evaluated.to_mesh_clear()


def _mesh_digest(mesh):
    digest = hashlib.blake2b(digest_size=32)
    _hash_column(digest, mesh.vertices, 'co', 'f', 3)
    _hash_column(digest, mesh.edges, 'vertices', 'i', 2)
    _hash_column(digest, mesh.loops, 'vertex_index', 'i', 1)
    _hash_column(digest, mesh.polygons, 'loop_start', 'i', 1)
    _hash_column(digest, mesh.polygons, 'loop_total', 'i', 1)
    return digest.digest()


def _hash_column(digest, rows, field, kind, width):
    values = array(kind, [0]) * (len(rows) * width)
    rows.foreach_get(field, values)
    digest.update(len(rows).to_bytes(8, 'little')); digest.update(values)


def remember_applied_scp_states(root, scene, ids=None):
    """Acknowledge the evaluated outputs of the SCP pass, without evaluating again."""
    layer = view_layer_for_scene(scene)
    if layer is None: return
    depsgraph = layer.depsgraph
    for scp in root.af_scp_system.scps:
        if ids is not None and str(scp.id) not in ids: continue
        objects = {scp.transform_object_ref, scp.geometry_object_ref} - {None}
        for obj in objects: _remember(_key(root, obj, depsgraph), _snapshot(obj, depsgraph))


@persistent
def clear_scp_states(_unused=None):
    _STATES.clear()


def register_scp_states():
    for name in _EVENTS:
        handlers = getattr(bpy.app.handlers, name)
        if clear_scp_states not in handlers: handlers.append(clear_scp_states)


def unregister_scp_states():
    clear_scp_states()
    for name in _EVENTS:
        handlers = getattr(bpy.app.handlers, name)
        if clear_scp_states in handlers: handlers.remove(clear_scp_states)
