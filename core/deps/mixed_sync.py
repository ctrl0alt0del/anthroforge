"""Evaluate existing geometry drivers in dependency order for layered surfaces."""
from .surface_dependencies import GEOMETRY, graph_for, waves, parents


def run(root, scene, full, impacted, bake, meta, profile, drivers, dispatch, post):
    geometry = {d.entity_types()[0]: d for d in drivers if len(d.entity_types()) == 1 and d.entity_types()[0] in GEOMETRY}
    for driver in drivers:
        if driver not in geometry.values() and driver.name != 'vcp_mirror_sync_driver':
            dispatch(driver, root, scene, full, impacted, bake, meta, profile)
    blocked = _geometry(root, scene, full, impacted, bake, meta, profile, geometry, dispatch)
    mirrors = {kind: set(ids) - {key for k, key in blocked if k == kind} for kind, ids in impacted.items()}
    for driver in drivers:
        if driver.name == 'vcp_mirror_sync_driver': dispatch(driver, root, scene, False, mirrors, bake, meta, profile)
        post(driver, root, scene, full, impacted, bake, profile)


def _geometry(root, scene, full, impacted, bake, meta, profile, drivers, dispatch):
    graph = graph_for(root); upstream = parents(graph)
    selected = {(kind, key) for kind, keys in impacted.items() if kind in GEOMETRY for key in keys}
    blocked = {row for row in upstream if row not in selected and not _current(root, scene, *row)}
    for wave in waves(graph, selected):
        for kind in GEOMETRY:
            ids = _ready(root, scene, wave, kind, upstream, blocked)
            if not ids: continue
            dispatch(drivers[kind], root, scene, False, {kind: ids}, bake, meta, profile)
            _publish_mirrors(root, scene, kind, ids)
            blocked.update((kind, key) for key in ids if not _current(root, scene, kind, key))
        blocked.update(row for row in wave if upstream.get(row, set()) & blocked)
    for kind, identity in blocked & selected: _stale(root, scene, kind, identity)
    return blocked


def _ready(root, scene, wave, kind, upstream, blocked):
    ids = set()
    for k, key in wave:
        if k != kind: continue
        if upstream.get((k, key), set()) & blocked or not _supports_current(root, scene, k, key): blocked.add((k, key))
        else: ids.add(key)
    return ids


def _supports_current(root, scene, kind, identity):
    if kind != 'FIBER': return True
    from ..vcp.attachment_surface import muscle_backed, support_objects
    fiber = next((f for f in root.af_vcp_system.fibers if f.id == identity), None)
    if fiber is None: return False
    if not muscle_backed(fiber): return True
    from ..scp_runtime.attachment_gate import attachments_enabled
    if not attachments_enabled(scene): return False
    try: support_objects(root, scene, fiber)
    except ValueError as error:
        from ..visualization.muscle_fiber_attachment import fail
        fail(root, scene, fiber, str(error)); return False
    return True


def _stale(root, scene, kind, identity):
    tag = kind.lower()
    for obj in scene.objects:
        if obj.get('af_root_name') != root.name: continue
        if obj.get('af_' + tag + '_id') != identity and obj.get('af_source_' + tag + '_id') != identity: continue
        obj['af_' + tag + '_output_state'] = 'STALE'
        if not obj.get('af_attachment_error'): obj['af_attachment_error'] = 'Waiting for a current upstream attachment surface.'


def _publish_mirrors(root, scene, kind, ids):
    if kind not in {'MUSCLE', 'FIBER'}: return
    from ..visualization.vcp_mirror_runtime import sync_vcp_mirrors
    sync_vcp_mirrors(root, scene, ids if kind == 'FIBER' else (), ids if kind == 'MUSCLE' else (), (), ())


def _current(root, scene, kind, identity):
    if kind == 'FIBER':
        objects = [o for o in scene.objects if o.get('af_root_name') == root.name and o.get('af_fiber_id') == identity
                   and o.get('af_fiber_proxy') and not o.get('af_fiber_mirror_proxy')]
        return bool(objects and objects[0].get('af_fiber_output_state') == 'CURRENT')
    if kind == 'FIBER_SURFACE':
        from ..visualization.fiber_surface_sync import find_fiber_surface_proxy
        obj = find_fiber_surface_proxy(scene, root.name, identity)
        return bool(obj and obj.get('af_fiber_surface_output_state') == 'CURRENT')
    if kind == 'MUSCLE':
        from ..visualization.muscle_sync_helpers import resolve_muscle_surface
        obj = resolve_muscle_surface(root, identity, 'BASE', scene)
        return bool(obj and obj.get('af_muscle_output_state', 'CURRENT') == 'CURRENT')
    return True
