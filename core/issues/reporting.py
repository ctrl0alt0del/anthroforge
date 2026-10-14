"""Producer-scoped transactions: old results survive failed or superseded checks."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    scope: tuple
    provider: str
    generation: int
    epoch: int


class Reporting:
    def __init__(self, repository):
        self.repository, self.generations, self.epoch = repository, {}, 0

    def begin_check(self, scope, provider):
        key = scope, provider
        generation = self.generations.get(key, 0) + 1
        self.generations[key] = generation
        self.repository.state(scope, "CHECKING", generation, provider=provider)
        return Check(scope, provider, generation, self.epoch)

    def current(self, check):
        return check.epoch == self.epoch and self.generations.get((check.scope, check.provider)) == check.generation

    def complete_check(self, check, records, metadata=None):
        if not self.current(check):
            return False
        self.repository.replace(check.scope, records, check.generation, metadata, check.provider)
        return True

    def fail_check(self, check, error, cancelled=False):
        if not self.current(check):
            return False
        self.repository.state(check.scope, "CANCELLED" if cancelled else "FAILED",
                              check.generation, str(error), check.provider)
        return True

    def report(self, issue):
        self.repository.upsert(issue)

    def reset(self):
        self.epoch += 1
        self.generations.clear()


    def invalidate(self, scope, provider):
        key = scope, provider
        self.generations[key] = self.generations.get(key, 0) + 1
        self.repository.state(scope, "UNSCANNED", self.generations[key], provider=provider)
