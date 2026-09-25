"""Persisted calibrated views and geometry-bound visual inspection operations."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.authoring import visual_camera as camera, visual_mesh as mesh, visual_raster as raster, visual_images as images
from ...core.authoring import visual_context
from . import visual_subjects


def views(service, request):
    service.check(request['params'])
    params = visual_subjects.prepare(service, request['params'])
    neighbors, selection = visual_context.context(service.inventory, params['instance_id'], params)
    scene = mesh.snapshot(service.inventory, params['instance_id'], neighbors)
    scene['neighborhood'] = selection
    key = digest(scene)
    service.store.put('v04_visual_scenes', key, scene)
    geometry = scene['geometry'][scene['owner']]
    rows = [save_view(service, key, scene, camera.make(geometry, direction, params.get('resolution', 512)), name) for name, direction in camera.DIRECTIONS.items()]
    report = visual_context.packet(scene, selection, service.inventory)
    return dict(views=rows, inspection=report, assets=[v['image'] for v in rows]+[service.store.asset(report, 'inspection_measurements'), images.index(service.store, rows, 'Geometry '+params['instance_id'], service.inventory['scene_id'])])


def save_view(service, scene_id, scene, spec, label, section=None, display=None):
    from ...core.authoring.visual_overlay import decorate
    from ...core.authoring.visual_labels import identity
    data = dict(snapshot_id=scene_id, scene_revision=scene['scene_revision'], owner=scene['owner'], camera=spec, label=label, section=mesh.section_valid(section) or {}, display=display or {})
    data['legend'] = {identity(key, 'O'): scene.get('names', {}).get(key, key)+' ['+key+']' for key in scene['geometry']}
    data['id'] = digest(data)
    result = raster.render(scene, spec, section)
    data['image'] = images.image(service.store, decorate(raster.shade(result, spec, scene['owner']), result, scene, data))
    data['visible_triangles'] = sorted(set(result['ids'].ravel().tolist())-{-1})
    service.store.put('v04_visual_views', data['id'], data)
    return {k: v for k, v in data.items() if k != 'visible_triangles'}


def load_view(service, identity):
    view = service.store.get('v04_visual_views', identity)
    require(view is not None, 'VIEW_NOT_FOUND')
    scene = service.store.get('v04_visual_scenes', view['snapshot_id'])
    require(scene is not None and digest(scene) == view['snapshot_id'], 'VIEW_SNAPSHOT_INVALID')
    require(scene['root_id'] == (service.inventory['root_id'] or service.inventory['scene_id']), 'VIEW_ROOT_MISMATCH')
    visual_subjects.refresh(service, scene)
    require(mesh.current(scene, service.inventory), 'STALE_VIEW')
    return view, scene


def view(service, request):
    params = dict(request['params'])
    source, scene = load_view(service, params['view_id'])
    scene_id, scene = context_scene(service, source, scene, params)
    if params.get('point_id'):
        from .visual_points import load_points
        require('center' not in params, 'VIEW_FOCUS_AMBIGUOUS')
        params['center'] = load_points(service, [params['point_id']], scene_id)[0]['point']
    spec = camera.orbit(scene['geometry'][scene['owner']], source['camera'], params)
    section = {} if params.get('clear_section') else params.get('section', source['section'])
    require(not params.get('clear_section') or 'section' not in params, 'VIEW_SECTION_AMBIGUOUS')
    row = save_view(service, scene_id, scene, spec, params.get('label', 'CUSTOM'), section, params.get('display', source.get('display')))
    report = visual_context.packet(scene, scene.get('neighborhood', {}), service.inventory)
    return dict(view=row, inspection=report, assets=[row['image'], service.store.asset(report, 'inspection_measurements')])


def context_scene(service, source, scene, params):
    if not {'context_ids', 'context_objects', 'automatic_context', 'neighbor_distance'} & set(params):
        return source['snapshot_id'], scene
    subject = dict(source_object=scene['object_sources'][scene['owner']]) if scene['owner'] in scene.get('object_sources', {}) else dict(instance_id=scene['owner'])
    params = visual_subjects.prepare(service, dict(params, **subject))
    neighbors, _selection = visual_context.context(service.inventory, scene['owner'], params)
    current = mesh.snapshot(service.inventory, scene['owner'], neighbors)
    current['neighborhood'] = _selection
    identity = digest(current)
    service.store.put('v04_visual_scenes', identity, current)
    return identity, current


def operations():
    from . import visual_points, visual_regions, visual_coverage
    result = {'anatomy.views': views, 'anatomy.view': view, 'anatomy.coverage': visual_coverage.coverage}
    result.update({'anatomy.'+name: getattr(visual_points, name) for name in ('pick', 'highlight')})
    result.update({'anatomy.'+name: getattr(visual_regions, name) for name in ('select_region', 'inspect_selection', 'propose_region')})
    return result
