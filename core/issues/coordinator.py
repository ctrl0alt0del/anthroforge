"""One resumable, generation-checked scheduler for all warning factories."""
from collections import OrderedDict, Counter
from time import perf_counter
from dataclasses import dataclass


@dataclass(frozen=True)
class WakeAfter:
    seconds: float


def close_iterator(iterator):
    close = getattr(iterator, 'close', None)
    if close is not None and not getattr(iterator, 'gi_running', False): close()


class Coordinator:
    def __init__(self, repository, clock=perf_counter):
        self.repository, self.clock = repository, clock
        self.factories, self.jobs, self.generations = {}, OrderedDict(), {}
        self.metrics = Counter()
        self.ready_at = {}

    def register(self, provider):
        if provider.name in self.factories:
            raise ValueError("Duplicate warning provider")
        self.factories[provider.name] = provider

    def check_all(self, context):
        self._dispatch("check_all", context)

    def on_action(self, event, context):
        self._dispatch("on_action", event, context)

    def _dispatch(self, method, *args):
        for factory in tuple(self.factories.values()):
            try:
                getattr(factory, method)(*args)
                self._recovered(factory.name)
            except Exception as error:
                scope = ("runtime", "", "", "FILE", factory.name, 0)
                self.repository.state(scope, "FAILED", error=error, provider=factory.name)
                self.metrics["listener_failures"] += 1

    def _recovered(self, provider):
        scope = ("runtime", "", "", "FILE", provider, 0)
        if scope in self.repository.states:
            self.repository.remove(scope)

    def enqueue(self, scope, builder, delay=0.0):
        self.cancel(scope)
        token = self.generations.get(scope, 0) + 1
        self.generations[scope] = token
        self.jobs[scope] = (token, iter(builder(token)))
        self.ready_at[scope] = self.clock() + delay if delay > 0 else 0.
        return token

    def current(self, scope, token):
        return self.generations.get(scope) == token

    def cancel(self, scope):
        job = self.jobs.pop(scope, None)
        self.ready_at.pop(scope, None)
        self.generations[scope] = self.generations.get(scope, 0) + 1
        if job is not None:
            close_iterator(job[1])
            self.metrics["cancelled"] += 1

    def cancel_all(self):
        for scope in tuple(self.jobs):
            self.cancel(scope)
        for (scope, provider), state in tuple(self.repository.provider_states.items()):
            self.repository.state(scope, "CANCELLED", state["generation"], provider=provider)

    def tick(self, budget_ms=4.0, max_steps=128):
        started, steps = self.clock(), 0
        with self.repository.batch():
            while self.jobs and steps < max_steps:
                now = self.clock() if steps else started
                if steps and (now - started) * 1000 >= budget_ms: break
                scope = next((key for key in self.jobs if self.ready_at.get(key, 0) <= now), None)
                if scope is None: break
                self._step(scope)
                steps += 1
        elapsed = (self.clock() - started) * 1000
        self.metrics["duration_ms"] += elapsed
        self.metrics["max_tick_ms"] = max(elapsed, self.metrics["max_tick_ms"])
        return bool(self.jobs)

    def _step(self, scope):
        token, iterator = self.jobs[scope]
        try:
            value = next(iterator)
            if not self.current(scope, token): return close_iterator(iterator)
            if isinstance(value, WakeAfter): self.ready_at[scope] = self.clock()+value.seconds
        except StopIteration:
            if self.current(scope, token): self._discard(scope)
        except Exception as error:
            if self.current(scope, token): self._fail(scope, token, error)

    def _discard(self, scope):
        self.jobs.pop(scope, None)
        self.ready_at.pop(scope, None)

    def _fail(self, scope, token, error):
        self._discard(scope); self.metrics['failures'] += 1
        provider, target = scope if isinstance(scope, tuple) and len(scope) == 2 else (None, scope)
        if isinstance(target, tuple) and len(target) > 3 and target[3] == 'FILE':
            self.repository.discovery = 'FAILED'
        kwargs = {} if provider is None else dict(provider=provider)
        self.repository.state(target, 'FAILED', token, error, **kwargs)
