"""Explicit fixes only; registered solvers supply applicability and cancellation."""
from dataclasses import dataclass

TERMINAL = {"DONE", "FAILED", "CANCELLED", "UNRESOLVED"}


@dataclass(frozen=True)
class Solver:
    name: str
    label: str
    codes: tuple
    applicable: object
    invoke: object
    cancel: object = None
    poll: object = None


class Resolution:
    def __init__(self, repository, listening):
        self.repository, self.listening, self.solvers, self.running = repository, listening, {}, {}

    def register(self, solver):
        if solver.name in self.solvers:
            raise ValueError("Duplicate issue solver")
        self.solvers[solver.name] = solver
        return lambda: self.solvers.pop(solver.name, None)

    def available(self, issue, context=None):
        state = self.repository.provider_states.get((issue.entity.scope, issue.provider), {})
        if state.get("status") != "COMPLETE":
            return ()
        return tuple(s for s in self.solvers.values() if issue.code in s.codes and s.applicable(issue, context))

    def invoke(self, identity, name, context=None):
        issue, solver = self.repository.records[identity], self.solvers[name]
        if identity in self.running and self.running[identity]["state"] not in TERMINAL:
            raise ValueError("A fix is already active for this issue")
        if solver not in self.available(issue, context):
            raise ValueError("Issue is stale or the fix is not applicable; recheck first")
        result = solver.invoke(issue, context)
        self.running[identity] = dict(solver=name, state="REQUESTED", result=str(result), issue=issue, context=context)
        return result

    def complete(self, identity, context=None):
        job = self.running[identity]
        job["state"] = "VERIFYING"
        job["prior_state"] = self._provider_state(job)
        self.listening.recheck(job["issue"].provider, context or job["context"])

    def cancel(self, identity, context=None):
        job = self.running.get(identity)
        solver = None if job is None else self.solvers.get(job["solver"])
        if solver is not None and solver.cancel is not None:
            solver.cancel(job["issue"], context or job["context"])
            job["state"] = "CANCELLED"

    def tick(self):
        for identity, job in tuple(self.running.items()):
            try:
                self._tick_job(identity, job)
            except Exception as error:
                job.update(state="FAILED", error=str(error))
        return any(job["state"] not in TERMINAL for job in self.running.values())

    def _tick_job(self, identity, job):
        if job["state"] in TERMINAL:
            return
        if job["state"] == "VERIFYING":
            return self._verify(job)
        solver = self.solvers[job["solver"]]
        if solver.poll is not None:
            job["state"] = solver.poll(job["issue"], job["context"])
            if job["state"] == "DONE":
                self.complete(identity)

    def _provider_state(self, job):
        issue = job["issue"]
        return self.repository.provider_states.get((issue.entity.scope, issue.provider))

    def _verify(self, job):
        state = self._provider_state(job)
        if state is None:
            job["state"] = "DONE"
        elif state is not job["prior_state"] and state["status"] == "COMPLETE":
            issue = job["issue"]
            remains = any(row.code == issue.code and row.provider == issue.provider
                          and row.entity.scope == issue.entity.scope for row in self.repository.records.values())
            job["state"] = "UNRESOLVED" if remains else "DONE"
        elif state["status"] in {"FAILED", "CANCELLED"}:
            job.update(state="FAILED", error=state.get("error", "Verification failed"))
