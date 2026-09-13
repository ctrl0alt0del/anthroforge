"""One resumable, generation-checked scheduler for all warning factories."""
from collections import OrderedDict, Counter
from time import perf_counter


class Coordinator:
    def __init__(self, repository, clock=perf_counter):
        self.repository, self.clock = repository, clock
        self.factories, self.jobs, self.generations = {}, OrderedDict(), {}
        self.metrics = Counter()

    def register(self, provider):
        if provider.name in self.factories:
            raise ValueError("Duplicate warning provider")
        self.factories[provider.name] = provider

    def check_all(self, context):
        for factory in self.factories.values():
            factory.check_all(context)

    def on_action(self, event, context):
        for factory in self.factories.values():
            factory.on_action(event, context)

    def enqueue(self, scope, builder):
        self.cancel(scope)
        token = self.generations.get(scope, 0) + 1
        self.generations[scope] = token
        self.jobs[scope] = (token, iter(builder(token)))
        return token

    def current(self, scope, token):
        return self.generations.get(scope) == token

    def cancel(self, scope):
        job = self.jobs.pop(scope, None)
        self.generations[scope] = self.generations.get(scope, 0) + 1
        if job is not None:
            close = getattr(job[1], "close", None)
            if close is not None and not getattr(job[1], "gi_running", False):
                close()
            self.metrics["cancelled"] += 1

    def cancel_all(self):
        for scope in tuple(self.jobs):
            self.cancel(scope)
        for (scope, provider), state in tuple(self.repository.provider_states.items()):
            self.repository.state(scope, "CANCELLED", state["generation"], provider=provider)

    def tick(self, budget_ms=8.0, max_steps=32):
        started, steps = self.clock(), 0
        while self.jobs and steps < max_steps:
            if steps and (self.clock() - started) * 1000 >= budget_ms:
                break
            scope = next(iter(self.jobs))
            self._step(scope); steps += 1
        elapsed = (self.clock() - started) * 1000
        self.metrics["duration_ms"] += elapsed
        self.metrics["max_tick_ms"] = max(elapsed, self.metrics["max_tick_ms"])
        return bool(self.jobs)

    def _step(self, scope):
        token, iterator = self.jobs[scope]
        try:
            next(iterator)
        except StopIteration:
            if self.current(scope, token):
                self.jobs.pop(scope, None)
        except Exception as error:
            self.jobs.pop(scope, None); self.metrics["failures"] += 1
            if scope[3] == "FILE":
                self.repository.discovery = "FAILED"
            self.repository.state(scope, "FAILED", token, error)
