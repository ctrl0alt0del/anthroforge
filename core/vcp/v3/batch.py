"""Deterministic multi-Fiber coordinator for production V3 sessions."""

from dataclasses import dataclass
from time import perf_counter

from ..v2.collision import run_native_sweep_batch, run_native_sweep_serial
from ..v2.collision_native import native_worker_threads


@dataclass
class V3BatchEntry:
    key: tuple
    session: object
    priority: int
    ordinal: int
    age: int = 0


@dataclass(frozen=True)
class V3BatchReport:
    selected: tuple = ()
    submitted: int = 0
    completed: int = 0
    workers: int = 0
    native_ms: float = 0.0
    elapsed_ms: float = 0.0


class V3WeightedSchedulingPolicy:
    def select(self, entries, limit):
        active = tuple(row for row in entries if not row.session.done)
        ordered = sorted(active, key=lambda row: (-row.priority - row.age, row.ordinal))
        return tuple(ordered[:max(1, int(limit))])

    def note(self, entries, selected):
        chosen = {row.key for row in selected}
        for row in entries: row.age = 0 if row.key in chosen else min(32, row.age + 1)


class V3OpenMpExecutor:
    def __init__(self, minimum_parallel_ms=0.25, qualification_batches=2):
        self.minimum_parallel_ms = float(minimum_parallel_ms)
        self.qualification_batches = max(1, int(qualification_batches))
        self.samples = self.parallel_batches = self.serial_batches = 0
        self.mean_parallel_ms = 0.0

    def execute(self, sweeps):
        parallel = len(sweeps) > 1 and self.collect()
        result = run_native_sweep_batch(sweeps) if parallel else run_native_sweep_serial(sweeps)
        self._record(result, parallel)
        return result

    def collect(self):
        return self.samples < self.qualification_batches or self.mean_parallel_ms >= self.minimum_parallel_ms

    def _record(self, result, parallel):
        if not result["submitted"]: return
        self.parallel_batches += int(parallel); self.serial_batches += int(not parallel)
        if not parallel: return
        self.samples += 1; weight = 1.0 / self.samples
        self.mean_parallel_ms += weight * (result["elapsed_ms"] - self.mean_parallel_ms)

    def stats(self):
        return {"executor_parallel": self.parallel_batches, "executor_serial": self.serial_batches,
                "qualified_parallel_ms": self.mean_parallel_ms}


class V3BatchCoordinator:
    def __init__(self, policy=None, executor=None, worker_count=None):
        self.policy = policy or V3WeightedSchedulingPolicy()
        self.executor = executor or V3OpenMpExecutor()
        self.worker_count = worker_count or native_worker_threads
        self.entries = {}; self.ordinal = 0
        self.steps = self.submitted = self.parallel_steps = 0
        self.elapsed_ms = self.native_ms = 0.0
        self.deferred_single = None

    def add(self, key, session, priority=1):
        self.ordinal += 1
        self.entries[key] = V3BatchEntry(key, session, max(1, int(priority)), self.ordinal)

    def remove(self, key):
        self.entries.pop(key, None)
        if self.deferred_single == key: self.deferred_single = None

    def set_priority(self, key, priority):
        entry = self.entries.get(key)
        if entry is not None: entry.priority = max(1, int(priority))

    def clear(self):
        self.entries.clear()
        self.deferred_single = None

    def step(self, budget_ms, advance):
        started = perf_counter(); deadline = started + max(0.0, float(budget_ms)) / 1000.0
        entries = tuple(self.entries.values())
        selected = self.policy.select(entries, self.worker_count())
        chosen, sweeps = [], []
        for row in selected:
            if chosen and perf_counter() >= deadline: break
            chosen.append(row); sweep = self._prepare(row, advance)
            if sweep is not None: sweeps.append(sweep)
        stats = self._execute(sweeps, selected, entries); self.policy.note(entries, chosen)
        elapsed = 1000.0 * (perf_counter() - started)
        report = _batch_report(chosen, stats, elapsed)
        self._record(report)
        return report

    def _prepare(self, entry, advance):
        sweep = getattr(entry.session, "pending_native_sweep", None)
        if sweep is None and not entry.session.done: advance(entry.key)
        return getattr(entry.session, "pending_native_sweep", None)

    def _execute(self, sweeps, selected, entries):
        key = _single_sweep_key(selected, sweeps)
        collect = getattr(self.executor, "collect", lambda: True)()
        defer = collect and key is not None and len(entries) > 1 and self.deferred_single != key
        if defer:
            self.deferred_single = key
            return {"submitted": 0, "completed": 0, "workers": 0, "elapsed_ms": 0.0}
        self.deferred_single = None
        return self.executor.execute(sweeps)

    def _record(self, report):
        self.steps += 1; self.submitted += report.submitted
        self.parallel_steps += int(report.workers > 1)
        self.elapsed_ms += report.elapsed_ms; self.native_ms += report.native_ms

    def stats(self):
        values = {"steps": self.steps, "submitted": self.submitted,
                "parallel_steps": self.parallel_steps, "elapsed_ms": self.elapsed_ms,
                "native_ms": self.native_ms, "active": len(self.entries)}
        extra = getattr(self.executor, "stats", lambda: {})()
        return dict(values, **extra)


def _batch_report(selected, stats, elapsed):
    return V3BatchReport(tuple(row.key for row in selected), stats["submitted"],
        stats["completed"], stats["workers"], stats["elapsed_ms"], elapsed)


def _single_sweep_key(selected, sweeps):
    if len(sweeps) != 1: return None
    return next((row.key for row in selected
                 if getattr(row.session, "pending_native_sweep", None) is sweeps[0]), None)
