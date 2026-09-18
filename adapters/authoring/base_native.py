"""Append-only transaction for native fibers and uninflated Fiber Surfaces."""
from contextlib import contextmanager
import bpy
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.visualization.fiber_surface_sync import register_fiber_surface_sync
from ...core.visualization.fiber_sync_helpers import persisted_fiber_points
from ...core.visualization.vcp_mirror_runtime import sync_vcp_mirrors
from ...app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from .native import write_fiber, find
from .records import record
from .publication import verify_mesh


@contextmanager
def publish(root, scene, plan):
    saved = checkpoint(root); ids = {}
    try:
        with suppress_vcp_prop_updates():
            ids = {part['id']: write_part(root, scene, part, plan) for part in plan['parts']}
            surfaces = {r['surface'] for r in ids.values()}
            register_fiber_surface_sync().sync_root_to_scene(root, scene, surfaces)
            sync_vcp_mirrors(root, scene, {f for r in ids.values() for f in r['fibers']}, (), (), ())
            verify_surfaces(root, scene, plan, ids)
            yield dict(plan_id=plan['id'], native_ids=ids, fingerprint=fingerprint(root, scene, ids))
    except BaseException:
        rollback(root, saved)
        raise


def write_part(root, scene, part, plan):
    radius = plan['definition'].get('collision_radius', .002); fibers = []
    for row in part['fibers']:
        data = dict(id='base.'+plan['id'][:12]+'.'+row['id'], closed=False, collision_radius=radius,
                    anchors=[p['anchor'] for p in row['points']], points=row['solved_path'])
        fiber = write_fiber(root, scene, data); fibers.append(fiber.id)
        fiber.pop('af_authoring_symmetry', None)
        fiber['af_authoring_base_plan'] = plan['id']
    surface = _new_surface(root.af_vcp_system, part['id'], 'LOFT', False, False); _assign_refs(surface, fibers)
    surface['af_authoring_base_plan'] = plan['id']; surface['af_authoring_head_ids'] = part['head_ids']
    return dict(surface=surface.id, fibers=fibers, head_ids=part['head_ids'])


def verify_surfaces(root, scene, plan, ids):
    fibers = {f for row in ids.values() for f in row['fibers']}
    for part in plan['parts']:
        objects = [o for o in scene.objects if o.get('af_root_name') == root.name
                   and o.get('af_fiber_surface_id') == ids[part['id']]['surface'] and not o.get('af_mirror_proxy')]
        require(len(objects) == 1, 'BASE_PUBLICATION_FAILED', part['id'])
        verify_mesh(objects[0], part['base']['vertices'], part['id'])
    for obj in scene.objects:
        if obj.get('af_root_name') == root.name and obj.get('af_fiber_proxy') and (obj.get('af_source_fiber_id') or obj.get('af_fiber_id')) in fibers:
            obj.display_type = 'TEXTURED'; obj.hide_viewport = False; obj.hide_set(False)


def fingerprint(root, scene, ids):
    fibers = sorted({f for row in ids.values() for f in row['fibers']})
    surfaces = sorted({row['surface'] for row in ids.values()})
    require(all(find(root.af_vcp_system.fibers, f) for f in fibers), 'BASE_EXTERNAL_EDIT')
    require(all(find(root.af_vcp_system.fiber_surfaces, s) for s in surfaces), 'BASE_EXTERNAL_EDIT')
    rows = [record(find(root.af_vcp_system.fibers, f)) for f in fibers]
    rows += [record(find(root.af_vcp_system.fiber_surfaces, s)) for s in surfaces]
    paths = [[list(p) for p in (persisted_fiber_points(scene, root.name, f) or [])] for f in fibers]
    return digest([rows, paths])


def verify(root, scene, receipt):
    require(fingerprint(root, scene, receipt['native_ids']) == receipt['fingerprint'], 'BASE_EXTERNAL_EDIT')


def checkpoint(root):
    names = ('fibers', 'fiber_surfaces', 'authored_points')
    return dict(counts={n: len(getattr(root.af_vcp_system, n)) for n in names if hasattr(root.af_vcp_system, n)},
                objects=set(bpy.data.objects), meshes=set(bpy.data.meshes), curves=set(bpy.data.curves))


def rollback(root, saved):
    with suppress_vcp_prop_updates():
        for name, count in saved['counts'].items():
            collection = getattr(root.af_vcp_system, name)
            while len(collection) > count:
                collection.remove(len(collection)-1)
        for obj in set(bpy.data.objects)-saved['objects']:
            bpy.data.objects.remove(obj, do_unlink=True)
        for name in ('meshes', 'curves'):
            collection = getattr(bpy.data, name)
            for item in set(collection)-saved[name]:
                if item.users == 0:
                    collection.remove(item)
