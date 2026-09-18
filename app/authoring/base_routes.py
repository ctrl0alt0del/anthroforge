"""Detached native solver, starting with two pins and at most eight corrections."""
from time import perf_counter
import numpy as np
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.model import FiberPlan
from ...core.authoring.layout_reduction import lengths
from ...core.authoring.layout_routing import refine
from .layout_solving import anchor
from .base_pins import bind


class Route:
    def __init__(self, service, state, part, fiber):
        self.service, self.state, self.part, self.fiber = service, state, part, fiber
        self.reference = np.asarray(fiber['reference_path']); self.times = lengths(self.reference)
        self.records, self.last = {}, None

    def solve(self, indices):
        for index in indices:
            if index not in self.records:
                role = 'origin' if index == 0 else 'insertion' if index == len(self.reference)-1 else 'route'
                self.records[index] = bind(self.service, self.reference[index], role, self.fiber['across'],
                                          self.times[index], self.part['bindings'], self.state['domains'], self.state['radius'])
        hits = [self.records[i] for i in indices]
        plan = FiberPlan(self.fiber['id'], self.fiber['across'], tuple(anchor(h['anchor']) for h in hits),
                         tuple(self.times[indices]), len(self.reference), False, self.state['radius'])
        result = run(self.service, self.state, plan)
        self.last = dict(result, controls=hits); return self.last


def run(service, state, plan):
    state['budget'].check(); require(state['calls'] < state['params'].get('max_solver_calls', 64), 'BASE_SOLVER_CALL_BUDGET')
    remaining = state['budget'].milliseconds-(perf_counter()-state['budget'].started)*1000
    state['calls'] += 1
    try:
        points, _material, termination = service.solver.solve(plan, state['snapshot'], min(remaining, state['params'].get('solver_budget_ms', 2000)))
        return dict(path=np.asarray(points).tolist(), validated=True, termination=termination)
    except AuthoringError as error:
        preview = getattr(error, 'preview', {}).get('points', [])
        if error.code != 'FIBER_UNSAFE' or len(preview) < 2:
            raise
        return dict(path=np.asarray(preview).tolist(), validated=False, termination=error.code)


def solve_fiber(service, state, part, fiber):
    route = Route(service, state, part, fiber)
    try:
        result = refine(route.reference, route.solve, state['params']['tolerance'],
                        2+state['params'].get('max_middle_points', 2), state['budget'])
        fiber.update(status='ready', points=result['controls'], solved_path=result['path'],
                     corrections=result['corrections'], route_max_error=result['route_max_error'], termination=result['termination'])
    except AuthoringError as error:
        fiber.update(status='unresolved', diagnostic=dict(code=error.code, message=str(error)),
                     points=(route.last or {}).get('controls', []), solved_path=(route.last or {}).get('path', []))
    return fiber
