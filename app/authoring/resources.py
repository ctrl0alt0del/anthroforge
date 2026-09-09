"""Cooperative stage/fiber cancellation and independent authoring budgets."""
from ...core.authoring.errors import require
from ...core.authoring.model import Budget


class EvaluationGuard:
    def __init__(self, service, document):
        self.service = service
        self.key = [service.inventory['root_id'], document['document_id'], service.request_id]
        self.limits = dict(max_fibers=512, max_surface_vertices=1000000, max_milliseconds=180000)
        self.limits.update(document.get('limits', {}))
        self.budget = Budget(milliseconds=self.limits['max_milliseconds'])
        self.fibers, self.vertices = 0, 0

    def check(self):
        flag = self.service.store.get('v04_cancellation', self.key) or {}
        self.budget.cancelled = flag.get('cancelled', False)
        self.budget.check()

    def fiber(self, count=1):
        self.check()
        self.fibers += count
        require(self.fibers <= self.limits['max_fibers'], 'FIBER_BUDGET_EXHAUSTED')

    def surface(self, count):
        self.check()
        self.vertices += count
        require(self.vertices <= self.limits['max_surface_vertices'], 'SURFACE_BUDGET_EXHAUSTED')


class GuardedSolver:
    def __init__(self, solver, guard):
        self.solver, self.guard = solver, guard

    def solve(self, plan, snapshot, budget_ms):
        self.guard.fiber()
        result = self.solver.solve(plan, snapshot, budget_ms)
        self.guard.check()
        return result


def cancel(service, request):
    params = request['params']
    key = [service.inventory['root_id'], params['document_id'], params['compilation_request_id']]
    service.store.put('v04_cancellation', key, dict(cancelled=True))
    return dict(state='cancellation_requested')
