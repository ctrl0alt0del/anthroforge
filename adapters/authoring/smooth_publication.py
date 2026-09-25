"""Atomic publication of shared Free fibers, coordinated surfaces and muscles."""
from contextlib import contextmanager
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.codec import digest
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...app.authoring.native_free import create
from ...app.use_cases.fiber_surface_create import _new_surface, _assign_refs, create_native_muscle
from ...core.visualization.fiber_surface_sync import register_fiber_surface_sync, evaluate_surface_record
from ...core.visualization.vcp_mirror_runtime import sync_vcp_mirrors
from ..free_fiber_transaction import snapshot, restore, release
from .records import record


@contextmanager
def publish(root, scene, preview):
    saved = snapshot(root, scene)
    try:
        ids = write(root, scene, preview); verify_geometry(root, scene, preview, ids)
        yield dict(native_ids=ids, fingerprint=fingerprint(root, scene, ids), preview_id=preview['id'])
    except BaseException:
        restore(root, scene, saved); raise
    finally: release(saved)


def write(root, scene, preview):
    fibers, ids = {}, {}; family = preview['definition']['family']
    for part in preview['parts']:
        for row in part['fibers']:
            key = tuple(row['key'])
            if key not in fibers: fibers[key] = create(root, scene, fiber_input(row, preview, family), True).id
    with suppress_vcp_prop_updates():
        for part in preview['parts']: ids[part['id']] = write_surface(root, part, fibers, preview)
    register_fiber_surface_sync().sync_root_to_scene(root, scene, {x['surface'] for x in ids.values()})
    for part in preview['parts']: ids[part['id']]['muscle'] = write_muscle(root, scene, ids[part['id']]['surface'], part, preview)
    sync_vcp_mirrors(root, scene, set(fibers.values()), (), (), ())
    visible(scene, root, set(fibers.values())); return ids


def fiber_input(row, preview, family):
    name = 'smooth.'+preview['id'][:16]+'.'+'.'.join(map(str, row['key']))
    samples = [dict(sample_id=name+'.'+str(i), co=p) for i, p in enumerate(row['path'])]
    tags, attachments = [], []
    for index, role, hit in ((0, 'START', row['endpoints'][0]), (len(samples)-1, 'END', row['endpoints'][1])):
        point_id = name+'.'+role
        tags.append(dict(occurrence_id=point_id, point_id=point_id, sample_id=samples[index]['sample_id'], role=role))
        attachments.append(dict(point_id=point_id, **hit['attachment'], normal_offset=hit.get('normal_offset', 0.)))
    return dict(name=family+' '+'.'.join(map(str, row['key'])), attachments=attachments,
        path=dict(representation='POLY', space='WORLD', samples=samples, structural=tags),
        settings=dict(collision_radius=preview['definition']['settings'].get('collision_radius', .002)))


def write_surface(root, part, fibers, preview):
    surface = _new_surface(root.af_vcp_system, preview['definition']['family']+' '+part['id'], 'LOFT', False, False)
    ids = [fibers[tuple(f['key'])] for f in part['fibers']]; _assign_refs(surface, ids)
    correspondence(root, surface, part, ids)
    surface['af_authoring_base_plan'] = preview['id']; surface['af_authoring_head_ids'] = part['head_ids']
    return dict(surface=surface.id, fibers=ids, head_ids=part['head_ids'])


def correspondence(root, surface, part, ids):
    from ...core.vcp.free_path import decode
    from ...core.vcp.free_surface_stations import KEY
    from ...core.authoring.codec import encode
    rows = []
    for identity, row in zip(ids, part['fibers']):
        fiber = next(f for f in root.af_vcp_system.fibers if f.id == identity)
        samples = decode(fiber.free_path_json)['samples']
        rows.append(dict(fiber_id=identity, sample_ids=[s['sample_id'] for s in samples], reference_points=[s['co'] for s in samples], stations=row['stations']))
    surface[KEY] = encode(dict(version=1, rows=rows))


def write_muscle(root, scene, surface, part, preview):
    config = dict(mode='control_point', native=dict(inflation_enabled=False))
    muscle = create_native_muscle(root, scene, surface, preview['definition']['family']+' '+part['id'], config)
    muscle['af_authoring_family'] = preview['definition']['family']; muscle['af_authoring_head_ids'] = part['head_ids']
    if part['output_domain']['mode'] != 'full':
        from ...app.use_cases.muscle_domain import configure
        configure(root, scene, muscle.id, part['output_domain'])
    muscle['af_authoring_smooth_base'] = preview['id']; return muscle.id


def verify_geometry(root, scene, preview, ids):
    from .smooth_quality import distances, combined
    from .smooth_domains import clipped
    assembled = []
    for part in preview['parts']:
        identity = ids[part['id']]['surface']; surface = next(s for s in root.af_vcp_system.fiber_surfaces if s.id == identity)
        result = evaluate_surface_record(root, scene, surface); actual = np.asarray(result.vertices); quads = np.asarray(result.faces)
        faces = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]))
        expected = np.asarray(part['native']['vertices']); tolerance = max(1e-6, float(np.linalg.norm(np.ptp(expected, axis=0)))*2e-6)
        error = max(distances(actual, expected, part['native']['triangles']).max(), distances(expected, actual, faces).max())
        require(error <= tolerance, 'BASE_PUBLICATION_MISMATCH', part['id'])
        assembled.append(dict(native=clipped(actual, faces, part.get('world_plane'))))
    require(not combined(assembled)['crossing_pairs'], 'BASE_PUBLICATION_FOLD')


def visible(scene, root, fibers):
    for obj in scene.objects:
        if obj.get('af_root_name') == root.name and obj.get('af_fiber_proxy') and (obj.get('af_source_fiber_id') or obj.get('af_fiber_id')) in fibers:
            obj.display_type = 'TEXTURED'; obj.hide_viewport = False; obj.hide_set(False)


def fingerprint(root, scene, ids):
    fiber_ids = {f for p in ids.values() for f in p['fibers']}; surfaces = {p['surface'] for p in ids.values()}; muscles = {p['muscle'] for p in ids.values()}
    rows = []; found = [0, 0, 0]
    for i, (name, names) in enumerate((('fibers', fiber_ids), ('fiber_surfaces', surfaces), ('muscles', muscles))):
        for item in getattr(root.af_vcp_system, name):
            if item.id in names:
                rows.append(record(item)); found[i] += 1
    require(found == [len(fiber_ids), len(surfaces), len(muscles)], 'BASE_EXTERNAL_EDIT')
    return digest(rows)


def verify(root, scene, receipt):
    require(fingerprint(root, scene, receipt['native_ids']) == receipt['fingerprint'], 'BASE_EXTERNAL_EDIT')
