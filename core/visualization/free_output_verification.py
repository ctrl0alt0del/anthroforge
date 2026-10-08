"""Verify dependent publications before an explicit Free transaction completes."""
from .fiber_surface_sync import evaluate_surface_record, find_fiber_surface_proxy
from .muscle_numeric_runtime import capture_muscle_work, execute_muscle_work, mesh_matches
from .muscle_sync import register_muscle_sync


def affected_surfaces(root, fiber_ids):
    surfaces = tuple(root.af_vcp_system.fiber_surfaces)
    affected = {s.id for s in surfaces if fiber_ids.intersection(r.fiber_id for r in s.fiber_refs)}
    while True:
        expanded = affected | {s.id for s in surfaces if s.construction_mode == 'BRANCHED_LOFT'
                               and affected.intersection((s.main_surface_id, *(b.surface_id for b in s.branches)))}
        if expanded == affected: return [s for s in surfaces if s.id in affected]
        affected = expanded


def verify_outputs(root, scene, fiber_ids):
    surfaces = affected_surfaces(root, set(fiber_ids)); ids = {s.id for s in surfaces}
    for surface in surfaces: _surface(root, scene, surface)
    muscles = [m for m in root.af_vcp_system.muscles if
               (m.fiber_surface_id in ids if m.surface_source_mode == 'FIBER_SURFACE'
                else set(fiber_ids).intersection(r.fiber_id for r in m.fiber_refs))]
    if muscles: _muscles(root, scene, muscles)
    _mirrors(root, scene, fiber_ids, muscles)


def _surface(root, scene, surface):
    result = evaluate_surface_record(root, scene, surface)
    proxy = find_fiber_surface_proxy(scene, root.name, surface.id)
    _published(proxy, 'af_fiber_surface_output_state', result.vertices, result.faces, surface.id)


def _published(obj, state, vertices, faces, identity):
    if obj is None or obj.get(state) != 'CURRENT' or not mesh_matches(obj, vertices, faces):
        raise ValueError('FREE_OUTPUT_NOT_CURRENT: ' + identity)


def _muscles(root, scene, muscles):
    sync = register_muscle_sync(); collection = sync._get_vis_collection(scene)
    work = [capture_muscle_work(sync, collection, root, scene, root.af_vcp_system, m) for m in muscles]
    for item in work:
        if item.error or item.stale or item.request is None:
            raise ValueError(item.error or 'FREE_OUTPUT_NOT_CURRENT: ' + item.muscle.id)
    batch = execute_muscle_work(scene, work)
    if len(batch.results) != len(work): raise ValueError('FREE_OUTPUT_NOT_CURRENT: incomplete muscle batch')
    for item, result in zip(work, batch.results):
        if result.error: raise ValueError(result.error)
        _published(item.base_obj, 'af_muscle_output_state', result.base_vertices, result.faces, item.muscle.id)
        _published(item.infl_obj, 'af_muscle_output_state', result.inflated_vertices, result.inflated_faces if result.inflated_faces is not None else result.faces, item.muscle.id)


def _mirrors(root, scene, fiber_ids, muscles):
    from . import vcp_mirror_runtime as mirror
    fibers = {f.id: f for f in root.af_vcp_system.fibers}; scps = {s.id: s for s in root.af_scp_system.scps}
    collection = register_muscle_sync()._get_vis_collection(scene)
    for key in fiber_ids:
        rule = mirror._rule_for_fiber(fibers[key], fibers, scps)
        _mirror(mirror._find_source_fiber_obj(collection, root.name, key), mirror._find_mirror_fiber_obj(collection, root.name, key), rule)
    for muscle in muscles:
        rule = mirror._rule_for_muscle(muscle, fibers, scps)
        for role in ('BASE', 'INFL'):
            from .muscle_sync_helpers import resolve_muscle_surface
            source = resolve_muscle_surface(root, muscle.id, role, scene)
            _mirror(source, mirror._find_mirror_muscle_obj(collection, root.name, muscle.id, role), rule)


def _mirror(source, mirrored, rule):
    from .mirror_rules import mirror_world_matrix
    if rule is None:
        if mirrored is not None: raise ValueError('FREE_OUTPUT_NOT_CURRENT: obsolete mirror')
        return
    expected = mirror_world_matrix(source.matrix_world, axis=rule[0], origin=rule[1]) if source else None
    if source is None or mirrored is None or mirrored.data != source.data or not _same_matrix(mirrored.matrix_world, expected):
        raise ValueError('FREE_OUTPUT_NOT_CURRENT: derived mirror')


def _same_matrix(actual, expected):
    # Blender decomposes object transforms on reload; retain mesh publication precision.
    return all(abs(a - b) <= 1e-6 for row, other in zip(actual, expected) for a, b in zip(row, other))
