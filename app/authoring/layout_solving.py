"""Solve only selected routes, starting with endpoints and a bounded correction loop."""
from time import perf_counter
import numpy as np
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.model import Anchor, Budget, FiberPlan
from ...core.authoring.layout_reduction import lengths
from ...core.authoring.layout_routing import refine


def solve_selected(service, params, domain, result):
    from .fiber_plans import decorate
    snapshot = service.scene.capture(params['scene_id'])
    require(snapshot.revision == service.inventory['revision'], 'STALE_SCENE_REVISION')
    state = dict(calls=0, budget=Budget(), snapshot=snapshot)
    for fiber in result['fibers']:
        route = NativeRoute(service, params, domain, fiber, state)
        solved = refine(route.reference, route.solve, params['tolerance'], params.get('max_points_per_fiber', 4), state['budget'])
        fiber.update(points=solved['controls'], solved_path=solved['path'], routing_corrections=solved['corrections'], route_max_error=solved['route_max_error'], termination=solved['termination'])
    decorate(result, [point for fiber in result['fibers'] for point in fiber['points']], params['region'])
    result.update(point_count=sum(len(f['points']) for f in result['fibers']), solver_calls=state['calls'], native_solver_validated=True)
    result['middle_point_count'] = result['point_count']-2*result['fiber_count']
    result['route_model'] = 'native_solver_with_sparse_corrections.v1'
    result['limitations'] = [note.replace('The pure geometric proposal requires native route validation.', 'The selected native fiber routes passed validation.') for note in result['limitations']]


class NativeRoute:
    def __init__(self, service, params, domain, fiber, state):
        self.service, self.params, self.domain, self.fiber, self.state = service, params, domain, fiber, state
        self.reference = np.asarray(fiber['reference_path'])
        self.records = {0: fiber['points'][0], len(self.reference)-1: fiber['points'][-1]}
        self.epsilon = max(1e-6, np.linalg.norm(np.ptp(np.concatenate(domain['polygons']), axis=0))*2e-7)

    def solve(self, indices):
        for index in indices:
            if index not in self.records:
                self.records[index] = self.pick(index)
        controls = [self.records[index] for index in indices]
        anchors = tuple(anchor(point['anchor']) for point in controls)
        stations = tuple(lengths(self.reference)[indices])
        plan = FiberPlan('layout.u'+str(self.fiber['candidate_index']), self.fiber['across'], anchors, stations, len(self.reference), False, self.params.get('collision_radius', .002))
        solved = self.run(plan)
        return dict(solved, controls=controls)

    def pick(self, index):
        from .fiber_plans import verify_hits, point_record
        params = dict(instance_id=self.domain['owner'], points=[self.reference[index].tolist()], max_distance=self.epsilon)
        if 'collision_radius' in self.params:
            params['collision_radius'] = self.params['collision_radius']
        hits = self.service.scene.snap_points(params, self.service.inventory)
        verify_hits(hits, self.domain, self.epsilon)
        return point_record(hits[0], 1, 3, self.params['region'])

    def run(self, plan):
        require(self.state['calls'] < self.params.get('max_solver_calls', 32), 'LAYOUT_SOLVER_CALL_BUDGET')
        self.state['budget'].check()
        remaining = self.state['budget'].milliseconds-(perf_counter()-self.state['budget'].started)*1000
        self.state['calls'] += 1
        try:
            points, _, termination = self.service.solver.solve(plan, self.state['snapshot'], min(remaining, self.params.get('solver_budget_ms', 2000)))
            return dict(path=np.asarray(points).tolist(), validated=True, termination=termination)
        except AuthoringError as error:
            if error.code != 'FIBER_UNSAFE' or len(getattr(error, 'preview', {}).get('points', [])) < 2:
                raise AuthoringError(error.code, str(error), error.pointer, error.related) from error
            return dict(path=error.preview['points'], validated=False, termination=error.code)


def anchor(record):
    binding = record['surface_binding']
    retained = tuple(binding['tri_vidx']), tuple(binding['tri_weights'])
    return Anchor(record['owner'], tuple(record['point']), tuple(record['normal']), tuple(record['surface']), record['offset'], retained)
