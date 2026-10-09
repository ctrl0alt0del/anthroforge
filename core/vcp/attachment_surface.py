"""Blender adapter for typed surface bindings and immutable capture metadata."""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from .surface_reference import reference, key, from_object, is_muscle
from .surface_target import target_payload, target_from_payload

_SUPPORTS = ContextVar('af_capture_supports', default=None)


@contextmanager
def support_scope():
    if _SUPPORTS.get() is not None:
        yield; return
    token = _SUPPORTS.set({})
    try: yield
    finally: _SUPPORTS.reset(token)


def resolve_object(root, scene, value, runtime=None):
    from ..visualization.surface_target_service import default_surface_target_service
    cache = runtime.setdefault('resolved_targets', {}) if runtime is not None else {}
    identity = key(value)
    if identity not in cache: cache[identity] = default_surface_target_service().resolve(root, scene, reference(value), runtime)
    resolved = cache[identity]
    if resolved is not None and resolved.readiness != 'CURRENT': raise ValueError(resolved.reason)
    return None if resolved is None else resolved.mesh_object


def seal_binding(obj, raw, runtime=None, scene=None):
    if raw is None or not from_object(obj).entity_id: return raw
    from .surface_topology import signature
    value = json.loads(raw)
    value['target'] = target_payload(from_object(obj))
    value['topology_signature'] = signature(obj, runtime, scene)
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def binding_matches(obj, raw, runtime=None, scene=None):
    if obj is None: return False
    if not obj.get('af_muscle_proxy') and '"target"' not in str(raw): return True
    return binding_value_matches(obj, binding_data(raw), runtime, scene)


def binding_data(raw):
    try: return json.loads(raw)
    except (ValueError, TypeError): return {}


def binding_value_matches(obj, value, runtime=None, scene=None):
    if obj is None: return False
    if not isinstance(value, dict): return False
    if 'target' not in value: return not bool(obj.get('af_muscle_proxy'))
    target, topology = binding_identity(obj, runtime, scene)
    return value['target'] == target and value.get('topology_signature') == topology


def binding_identity(obj, runtime=None, scene=None):
    cache = (runtime or {}).get('surface_cache', {}); identity = ('binding_identity', obj.as_pointer())
    if identity not in cache:
        from .surface_topology import signature
        cache[identity] = target_payload(from_object(obj)), signature(obj, runtime, scene)
    return cache[identity]


def muscle_objects(scene, root):
    result = {}
    for obj in scene.objects:
        if obj.type != 'MESH' or obj.get('af_root_name') != root.name or not obj.get('af_muscle_proxy'): continue
        if obj.get('af_muscle_surface') not in {'BASE', 'INFL'}: continue
        identity = key(from_object(obj))
        if identity in result: raise ValueError('Ambiguous muscle surface identity.')
        result[identity] = obj
    return result


def typed_objects(scene, root):
    result = muscle_objects(scene, root)
    result.update((key(from_object(o)), o) for o in scene.objects if o.type == 'MESH'
                  and o.get('af_root_name') == root.name and o.get('af_scp_geometry') and o.get('af_scp_mirror'))
    return result


def support_keys(fiber):
    cache = _SUPPORTS.get()
    identity = (fiber.as_pointer(), hasattr(fiber, 'source')) if cache is not None and hasattr(fiber, 'as_pointer') else None
    if identity is not None and identity in cache: return cache[identity]
    result = _support_keys(fiber)
    if identity is not None: cache[identity] = result
    return result


def _support_keys(fiber):
    from .fiber_modes import fiber_parent_ids
    explicit = tuple(str(row.target_id) for row in getattr(fiber, 'attachment_supports', ()))
    return tuple(dict.fromkeys((*fiber_parent_ids(fiber), *explicit)))


def muscle_backed(fiber):
    return any(is_muscle(value) for value in support_keys(fiber))


def support_objects(root, scene, fiber, runtime=None):
    values = {value: resolve_object(root, scene, value, runtime) for value in support_keys(fiber) if value}
    if any(obj is None for obj in values.values()): raise ValueError('A selected attachment support is missing.')
    return values
