"""Reversible RNA and generated-geometry memento shared by UI and authoring."""
import bpy
from .authoring.capture import native_records
from .authoring.records import plain
from ..core.vcp.prop_update_guard import suppress_vcp_prop_updates


def _owned(root, scene):
    return [obj for obj in scene.objects if obj.get('af_root_name') == root.name
            and any(obj.get(key) for key in ('af_fiber_proxy', 'af_fiber_surface_proxy', 'af_muscle_proxy', 'af_muscle_base', 'af_muscle_inflated'))]


def snapshot(root, scene):
    from ..app.authoring.native_branches import _runtime_memento
    objects = _owned(root, scene); data = {}
    for obj in objects:
        if obj.data is not None and obj.data.name not in data: data[obj.data.name] = obj.data.copy()
    rows = {obj.name: (obj.data.name if obj.data else None, _custom(obj), obj.matrix_world.copy()) for obj in objects}
    runtime = {f.id: _custom(f) for f in root.af_vcp_system.fibers}
    return dict(records=native_records(root), objects=rows, data=data, runtime=runtime,
                notifications=_runtime_memento(root, scene), root={k: plain(root[k]) for k in root.keys() if _root_key(k)})


def _custom(item):
    return {key: plain(item[key]) for key in item.keys()}


def _restore_custom(item, values):
    for key in tuple(item.keys()):
        if key not in values: del item[key]
    for key, value in values.items(): item[key] = value


def restore(root, scene, saved):
    from ..core.visualization.fiber_cache_lifecycle import invalidate_fiber_caches
    from ..app.authoring.native_branches import _restore_runtime
    _restore_native(root, saved)
    for obj in _owned(root, scene):
        if obj.name not in saved['objects']: bpy.data.objects.remove(obj, do_unlink=True)
    for name, (data, values, matrix) in saved['objects'].items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.data = saved['data'][data] if data else None
            _restore_custom(obj, values); obj.matrix_world = matrix
    invalidate_fiber_caches(scene, root)
    _restore_runtime(root, saved['notifications'])


def _root_key(key):
    return key.startswith(('af_free', 'af_authoring'))


def _restore_native(root, saved):
    from ..app.authoring.native_branches import _restore
    with suppress_vcp_prop_updates():
        _restore(root, saved['records'])
        for fiber in root.af_vcp_system.fibers: _restore_fiber(fiber, saved['runtime'][fiber.id])
        for key in tuple(root.keys()):
            if _root_key(key) and key not in saved['root']: del root[key]
        for key, value in saved['root'].items(): root[key] = value


def _restore_fiber(fiber, values):
    from ..core.vcp.fiber_authority import invalidate
    generation = int(fiber.get('af_path_authority', 0))
    _restore_custom(fiber, values)
    fiber['af_path_authority'] = generation
    invalidate(fiber)


def release(saved):
    for data in saved['data'].values():
        if data.users == 0:
            (bpy.data.curves if isinstance(data, bpy.types.Curve) else bpy.data.meshes).remove(data)


def run(root, scene, action):
    saved = snapshot(root, scene)
    try: return action()
    except Exception:
        restore(root, scene, saved)
        raise
    finally: release(saved)
