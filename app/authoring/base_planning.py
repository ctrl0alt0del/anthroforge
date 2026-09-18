"""Sparse native reconstruction of explicitly selected whole underside patches."""
import numpy as np
from ...core.authoring.codec import digest
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.model import Budget
from ...core.authoring import fiber_layout
from ...core.authoring.base_patch import topology
from ...core.vcp.fiber_surface import FiberSurfaceSpec, evaluate_fiber_surface
from .base_definitions import load_base
from .base_routes import solve_fiber
from .base_surfaces import serial
from .transfers import key
from .transfer_bindings import target_domain


def plan_base_fibers(service, request):
    params = request['params']; service.check(params); base = load_base(service, params['base_id'])
    require({p['patch_id'] for p in params['parts']} == {p['id'] for p in base['patches']}, 'BASE_PART_COVERAGE')
    require(len(params['parts']) == len(base['patches']), 'BASE_DUPLICATE_PART')
    domains = validate_bindings(service, params); saved = service.store.get('native_base_requests', key(service, request['request_id']))
    if saved is not None:
        return dict(saved, replayed=True)
    state = dict(params=params, snapshot=service.scene.capture(params['scene_id']), budget=Budget(), calls=0,
                 domains=domains, radius=params.get('collision_radius', .002))
    parts = [plan_part(service, state, base, part) for part in params['parts']]
    result = record_plan(service, params, base, parts, state['calls'])
    service.store.put('native_base_requests', key(service, request['request_id']), result)
    return result


def record_plan(service, params, base, parts, calls):
    result = dict(version='native_base.v1', base_id=base['id'], definition=params, scene_revision=service.inventory['revision'],
                  parts=parts, solver_calls=calls, status='ready' if all(p['status'] == 'ready' for p in parts) else 'unresolved')
    result['support_digest'] = digest(service.inventory['geometry']); result['id'] = digest(serial(result))
    service.store.put('native_base_plans', key(service, result['id']), serial(result))
    return dict(status='success' if result['status'] == 'ready' else 'unresolved',
                plan=summary(result), assets=[service.store.asset(serial(result), 'native_base_plan')])


def validate_bindings(service, params):
    cache = {}
    for part in params['parts']:
        for spec in part['bindings']:
            require(spec['across'][0] <= spec['across'][1], 'BASE_INVALID_BINDING_INTERVAL')
            require(spec.get('along', [0, 1])[0] <= spec.get('along', [0, 1])[1], 'BASE_INVALID_BINDING_INTERVAL')
            target_domain(service, spec, cache)
    return cache


def plan_part(service, state, base, part):
    patch = next(p for p in base['patches'] if p['id'] == part['patch_id'])
    output = dict(id=patch['id'], head_ids=patch['head_ids'], status='unresolved', fibers=[])
    try:
        audit = {}; params = state['params']; faces = np.asarray(patch['vertices'])[patch['triangles']]
        layout = fiber_layout.plan(list(faces), patch['corners'], params['tolerance'], audit=audit,
                                  candidate_count=params.get('candidate_count', 17), samples_per_fiber=params.get('samples_per_fiber', 65),
                                  max_fibers=params.get('max_fibers', 8), max_points_per_fiber=2, budget=state['budget'])
        output.update(layout); output['fibers'] = [dict(f, id=patch['id']+'.u'+str(f['candidate_index'])) for f in layout['fibers']]
        for fiber in output['fibers']:
            solve_fiber(service, state, part, fiber)
        finish_part(service, output, audit)
    except AuthoringError as error:
        output.update(status='unresolved', diagnostic=dict(code=error.code, message=str(error)))
    return output


def finish_part(service, part, audit):
    require(all(f['status'] == 'ready' for f in part['fibers']), 'BASE_ROUTES_UNRESOLVED')
    part['native_solver_validated'] = True
    part['middle_point_count'] = sum(len(f['points'])-2 for f in part['fibers'])
    part['point_count'] = sum(len(f['points']) for f in part['fibers'])
    rows = [f['solved_path'] for f in part['fibers']]
    surface = evaluate_fiber_surface(rows, FiberSurfaceSpec(target_node_count=part['samples_per_fiber']))
    triangles = np.array([(f[0], f[i], f[i+1]) for f in surface.faces for i in range(1, len(f)-1)], int)
    part['base'] = dict(vertices=surface.vertices, triangles=triangles.tolist())
    part['topology'] = topology(triangles); part['spatial_quality'] = service.scene.base_mesh_quality(surface.vertices, triangles)
    require(not part['spatial_quality']['nonadjacent_bvh_overlap_pairs'] and not part['spatial_quality']['degenerate_triangles'], 'BASE_NATIVE_FOLD')
    fiber_layout.recheck(part, audit)
    part.update(status='ready', limitations=['Sampled base fit only; inflation and anatomical acceptance are not evaluated.',
                'Whole underside is the target; only authored pins lie on SCP surfaces, with zero offset.',
                'Separate patches are coordinated parts; this operation does not invent branch junctions.'])


def summary(plan):
    return dict(id=plan['id'], version=plan['version'], status=plan['status'], base_id=plan['base_id'],
                parts=[{k: p[k] for k in ('id', 'head_ids', 'status', 'fiber_count', 'point_count', 'middle_point_count',
                                          'max_sampled_error', 'diagnostic') if k in p} for p in plan['parts']],
                inflation_fitted=False, anatomical_review='required')
