"""Persistent visual patch candidates with add/subtract and multi-view feedback."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.authoring import visual_selection as selection, visual_mesh as mesh, visual_raster as raster, visual_overlay as overlay, visual_images as images
from .visual import load_view


def select_region(service, request):
    params = request['params']
    view, scene = load_view(service, params['view_id'])
    require(params.get('selection_id') or params.get('mode', 'add') == 'add', 'VISUAL_SELECTION_REQUIRED')
    patches = selection.select(scene, view, params['polygon'])
    previous = load_selection(service, params['selection_id'], view['snapshot_id']) if params.get('selection_id') else None
    patches = selection.combine(previous['patches'], patches, params.get('mode', 'add')) if previous else patches
    value = dict(snapshot_id=view['snapshot_id'], scene_revision=scene['scene_revision'], owner=scene['owner'], topology_digest=mesh.topology(scene['geometry'][scene['owner']]), patches=patches, area=selection.area(scene['geometry'][scene['owner']], patches), view_ids=sorted(set((previous or {}).get('view_ids', [])+[view['id']])))
    value.update(id=digest(value), units='scene2', approximation='Orthographic polygon clipping with numerical depth tolerance; no anatomical identity inferred.')
    service.store.put('v04_visual_selections', value['id'], value)
    return dict(selection=value, assets=preview(service, view, scene, patches))


def load_selection(service, identity, snapshot_id):
    value = service.store.get('v04_visual_selections', identity)
    require(value is not None, 'VISUAL_SELECTION_NOT_FOUND')
    first, second = [service.store.get('v04_visual_scenes', key) for key in (value['snapshot_id'], snapshot_id)]
    require(mesh.compatible(first, second, value['owner']) and second['owner'] == value['owner'], 'VISUAL_SNAPSHOT_MISMATCH')
    return value


def preview(service, view, scene, patches):
    buffer = raster.render(scene, view['camera'], view['section'])
    pixels = raster.shade(buffer, view['camera'], scene['owner'])
    return [images.image(service.store, overlay.patches(pixels, buffer, scene, view, patches))]


def inspect_selection(service, request):
    params, rows = request['params'], []
    for identity in params['view_ids']:
        view, scene = load_view(service, identity)
        value = load_selection(service, params['selection_id'], view['snapshot_id'])
        rows.append(dict(id=identity, label=view['label'], image=preview(service, view, scene, value['patches'])[0]))
    return dict(selection=value, views=rows, assets=[v['image'] for v in rows])


def propose_region(service, request):
    from .bindings import save_candidate, summary
    params, record = request['params'], service.load(request['params'])
    service.check(params, record)
    value = service.store.get('v04_visual_selections', params['selection_id'])
    require(value is not None and value['area'] > 0, 'VISUAL_SELECTION_EMPTY')
    view, scene = load_view(service, value['view_ids'][0])
    proposal = region_proposal(service, record, params, value)
    proof = dict(selection_id=value['id'], topology_digest=value['topology_digest'], views=value['view_ids'])
    row = dict(proposal=proposal, inputs=proof, approximations=[value['approximation'], 'Triangle correspondence is required; anatomical placement remains unreviewed.'])
    candidate = save_candidate(service, record, params['requirement'], 'visual_selection.v1', row)
    candidate['previews'] += preview(service, view, scene, value['patches'])+[service.store.asset(dict(selection=value, snapshot=scene, view=view), 'visual_evidence')]
    service.store.put('v04_candidates', [params['document_id'], candidate['id']], candidate)
    return dict(candidate=summary(candidate), assets=candidate['previews'])


def region_proposal(service, record, params, value):
    from ...core.authoring import substrate
    from ...core.authoring.indexed_patches import bind
    from ...core.authoring.references import lookup
    spec = lookup(record['document'], params['frame'])
    owner = substrate.binding(record['document'], service.inventory, spec['owner'])
    require(owner['instance_id'] == value['owner'], 'REGION_OWNER_MISMATCH')
    query = bind(service.inventory['geometry'][value['owner']], value['patches'])
    evidence = dict(basis='designer_authored', sources=[], note=params['note'])
    region = dict(owner=spec['owner'], frame=params['frame'], reference_pose=service.inventory['reference_pose'], concept=params['concept'], query=query, evidence=evidence)
    return dict(kind='region', value=region)
