"""Plan point sets on a saved region, retaining the ordinary native picker payloads."""
import numpy as np
from ...core.authoring import fiber_layout, attachment_binding, indexed_patches
from ...core.authoring.clipping import point_in_polygon
from ...core.authoring.errors import require
from ...core.authoring.regions import RegionEvaluator
from ...core.authoring.layout_preview import svg
from .queries import resolved_document
from .layout_solving import solve_selected

LANDMARKS = ('start_left', 'start_right', 'end_right', 'end_left')
OPTIONS = ('candidate_count', 'samples_per_fiber', 'max_fibers', 'max_points_per_fiber')


def plan_fibers(service, request):
    params, record = request['params'], service.load(request['params'])
    service.check(params, record)
    domain = RegionEvaluator(resolved_document(service, record), service.inventory).evaluate(params['region'])
    geometry = service.inventory['geometry'][domain['owner']]
    corners = [attachment_binding.resolve(geometry, params['boundary_landmarks'][key])[0] for key in LANDMARKS]
    audit = {}
    result = fiber_layout.plan(domain['polygons'], corners, params['tolerance'], audit=audit, **{k: params[k] for k in OPTIONS if k in params})
    bind_plan(service, params, domain, result)
    solve_selected(service, params, domain, result)
    fiber_layout.recheck(result, audit)
    result.update(region=params['region'], owner=domain['owner'], region_area=domain['area'], topology_digest=indexed_patches.topology(geometry))
    result.update(boundary_landmarks=params['boundary_landmarks'], scene_revision=service.inventory['revision'], draft_revision=record['draft_revision'], region_definition_digest=domain['definition_digest'])
    result['limitations'].extend(domain['limitations'])
    return dict(plan=result, draft_revision=record['draft_revision'], assets=[service.store.image(svg(domain['polygons'], result))])


def bind_plan(service, params, domain, result):
    points = [point for fiber in result['fibers'] for point in fiber['points']]
    require(len(points) <= 2048, 'LAYOUT_POINT_BUDGET', 'At most 2,048 points can be bound per plan.')
    picker = getattr(service.scene, 'snap_points', None)
    require(callable(picker), 'UNSUPPORTED_CAPABILITY', 'Native surface point picking is unavailable.')
    epsilon = max(1e-6, np.linalg.norm(np.ptp(np.concatenate(domain['polygons']), axis=0))*2e-7)
    options = dict(instance_id=domain['owner'], max_distance=epsilon)
    if 'collision_radius' in params:
        options['collision_radius'] = params['collision_radius']
    hits = []
    for start in range(0, len(points), 256):
        hits.extend(picker(dict(options, points=points[start:start+256]), service.inventory))
    verify_hits(hits, domain, epsilon)
    decorate(result, hits, params['region'])


def verify_hits(hits, domain, epsilon):
    polygons = [np.asarray(p) for p in domain['polygons']]
    low, high = np.array([p.min(axis=0) for p in polygons]), np.array([p.max(axis=0) for p in polygons])
    for index, hit in enumerate(hits):
        require(hit['valid'], 'LAYOUT_ANCHOR_UNRESOLVED', f"Point {index}: "+'; '.join(d['code'] for d in hit['diagnostics']))
        point = np.asarray(hit['point'])
        candidates = np.flatnonzero(np.all(point >= low-epsilon, axis=1) & np.all(point <= high+epsilon, axis=1))
        require(any(point_in_polygon(point, polygons[i], epsilon) for i in candidates), 'SAMPLE_OUTSIDE_ALLOWED_REGION', f'Planned point {index} left the selected area.')


def decorate(result, hits, region):
    cursor = 0
    for fiber in result['fibers']:
        count = len(fiber['points'])
        fiber['points'] = [point_record(hit, index, count, region) for index, hit in enumerate(hits[cursor:cursor+count])]
        fiber['start'], fiber['end'] = fiber['points'][0], fiber['points'][-1]
        fiber['middle_points'] = fiber['points'][1:-1]
        fiber['route_anchors'] = [point['route_anchor'] for point in fiber['points']]
        fiber['reason'] = 'lateral_boundary' if fiber['across'] in (0., 1.) else 'sampled_band_error'
        cursor += count


def point_record(hit, index, count, region):
    role = 'start' if index == 0 else 'end' if index == count-1 else 'middle'
    route = dict(region=region, surface_binding=hit['anchor']['surface_binding'])
    if role == 'middle':
        route['offset'] = 0.
    return dict(role=role, anchor=hit['anchor'], attachment=hit['attachment'], route_anchor=route)
