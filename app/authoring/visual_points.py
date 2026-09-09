"""Point receipts and cross-view confirmation share a frozen mesh snapshot."""
from ...core.authoring.errors import require
from ...core.authoring import visual_pick, visual_raster as raster, visual_images as images
from .visual import load_view


def pick(service, request):
    params = request['params']
    view, scene = load_view(service, params['view_id'])
    hits = [visual_pick.pick(scene, view, uv) for uv in params['points']]
    for hit in hits:
        if hit['hit']:
            service.store.put('v04_visual_points', hit['id'], hit)
    return dict(hits=hits)


def load_points(service, identities, snapshot_id):
    from ...core.authoring.visual_mesh import compatible
    result = [service.store.get('v04_visual_points', identity) for identity in identities]
    require(all(result), 'VISUAL_POINT_NOT_FOUND')
    scene = service.store.get('v04_visual_scenes', snapshot_id)
    require(all(compatible(service.store.get('v04_visual_scenes', p['snapshot_id']), scene, p['owner']) for p in result), 'VISUAL_SNAPSHOT_MISMATCH')
    return result


def highlight(service, request):
    params = request['params']
    views = []
    for identity in params['view_ids']:
        view, scene = load_view(service, identity)
        points = load_points(service, params['point_ids'], view['snapshot_id'])
        rows = [visual_pick.project_hit(scene, view, hit) for hit in points]
        pixels = raster.shade(raster.render(scene, view['camera'], view['section']), view['camera'], scene['owner'])
        asset = images.image(service.store, visual_pick.markers(pixels, rows))
        views.append(dict(id=view['id'], label=view['label'], image=asset, projections=rows))
    return dict(views=views, assets=[v['image'] for v in views])
