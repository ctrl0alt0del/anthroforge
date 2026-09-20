"""Region-constrained native picking of endpoints and sparse underside guides."""
import numpy as np
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.nearest import nearest, on_triangles
from .transfer_bindings import target_domain
from .fiber_plans import verify_hits


def bind(service, guess, role, across, along, bindings, cache, radius):
    choices = [b for b in bindings if eligible(b, role, across, along)]
    require(choices, 'BASE_MISSING_PIN_REGION', f'No {role} region at across={across:.4g}, along={along:.4g}.')
    hits, errors = [], []
    for spec in choices:
        try:
            hits.append(pick(service, guess, spec, cache, radius))
        except AuthoringError as error:
            errors.append(error.code)
    require(hits, 'BASE_PIN_UNRESOLVED', ', '.join(sorted(set(errors))))
    return min(hits, key=lambda hit: hit['source_distance'])


def eligible(spec, role, across, along):
    return (spec['role'] == role and spec['across'][0]-1e-9 <= across <= spec['across'][1]+1e-9
            and spec.get('along', [0, 1])[0]-1e-9 <= along <= spec.get('along', [0, 1])[1]+1e-9)


def pick(service, guess, spec, cache, radius):
    domain = target_domain(service, spec, cache)
    triangles = region_triangles(domain)
    epsilon = max(1e-6, float(np.linalg.norm(np.ptp(triangles.reshape(-1, 3), axis=0)))*2e-7)
    hit = qualified_region_hit(service, guess, spec, domain, triangles, radius, epsilon)
    distance = float(np.linalg.norm(np.asarray(hit['point'])-guess))
    require(distance <= spec['max_distance'], 'BASE_PIN_TOO_FAR')
    check_facing(hit, spec)
    require(abs(hit['anchor']['offset']) < 1e-12, 'BASE_PIN_OFFSET')
    return dict(hit, source_guess=np.asarray(guess).tolist(), source_distance=distance, binding_spec=spec,
                region_definition_digest=domain['definition_digest'])


def qualified_region_hit(service, guess, spec, domain, triangles, radius, epsilon):
    nearest_point, _index = nearest(triangles, np.asarray(guess)); candidates = on_triangles(triangles, np.asarray(guess))
    order = np.argsort(np.linalg.norm(candidates-guess, axis=1))[:8]
    points = [nearest_point, *(candidates[order]*.9+triangles[order].mean(axis=1)*.1)]
    error = None
    for point in points:
        try:
            params = dict(instance_id=domain['owner'], points=[point.tolist()], collision_radius=radius, max_distance=spec['max_distance'])
            hit = service.scene.snap_points(params, service.inventory)[0]; verify_hits([hit], domain, epsilon)
            require(np.linalg.norm(np.asarray(hit['point'])-guess) <= spec['max_distance'], 'BASE_PIN_TOO_FAR')
            check_facing(hit, spec)
            return hit
        except AuthoringError as failure:
            error = error or failure
    raise error


def region_triangles(domain):
    triangles = np.asarray([[p[0], p[i], p[i+1]] for p in domain['polygons'] for i in range(1, len(p)-1)])
    require(len(triangles), 'BASE_PIN_REGION_EMPTY')
    cross = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    triangles = triangles[np.linalg.norm(cross, axis=1) > 1e-14]
    require(len(triangles), 'BASE_PIN_REGION_EMPTY')
    return triangles


def check_facing(hit, spec):
    if 'facing' in spec:
        direction = np.asarray(spec['facing'], float); length = np.linalg.norm(direction)
        require(length > 1e-10, 'BASE_INVALID_FACING')
        require(np.dot(direction/length, hit['normal']) >= spec.get('minimum_facing_dot', 0), 'BASE_WRONG_SIDE')
