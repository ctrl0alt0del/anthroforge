"""Deterministic multi-Fiber coordinator for production V3 sessions."""

from dataclasses import dataclass
import os
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
    controller_trials: int = 0


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


class V3NativeControllerExecutor:
    def __init__(self, target_ms=8.0, maximum_trials=8):
        self.target_ms = float(target_ms); self.maximum_trials = max(1, int(maximum_trials))
        self.trials = 1; self.batches = self.sessions = self.workers = 0; self.elapsed_ms = 0.0

    def execute(self, runs, budget_ms):
        from .native_controller import step_native_controllers
        report = step_native_controllers(runs, self.trials)
        self._record(report); self._adapt(report, budget_ms); return report

    def _record(self, report):
        self.batches += int(report["sessions"] > 0); self.sessions += report["sessions"]
        self.workers = max(self.workers, report["workers"]); self.elapsed_ms += report["elapsed_ms"]

    def _adapt(self, report, budget_ms):
        if not report["sessions"] or report["elapsed_ms"] <= 0.0: return
        target = min(self.target_ms, max(1.0, 0.7 * float(budget_ms)))
        proposal = round(self.trials * target / report["elapsed_ms"])
        self.trials = max(1, min(self.maximum_trials, round((self.trials + proposal) / 2)))

    def stats(self):
        return {"controller_batches": self.batches, "controller_sessions": self.sessions,
                "controller_workers": self.workers, "controller_native_ms": self.elapsed_ms,
                "controller_next_trials": self.trials}


class V3BatchCoordinator:
    def __init__(self, policy=None, executor=None, worker_count=None, controller_executor=None):
        self.policy = policy or V3WeightedSchedulingPolicy()
        self.executor = executor or V3OpenMpExecutor()
        self.controller_executor = controller_executor or V3NativeControllerExecutor()
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
        if _multi_session_enabled(): return self._step_controllers(budget_ms, advance)
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

    def _step_controllers(self, budget_ms, advance):
        started = perf_counter(); entries = tuple(self.entries.values())
        selected = self.policy.select(entries, max(1, 4 * self.worker_count()))
        chosen = self._prepare_controllers(selected, advance, started, budget_ms)
        ready = tuple((row, _controller_run(row.session)) for row in chosen)
        ready = tuple((row, run) for row, run in ready if run is not None and not run.done)
        stats = self._execute_controllers(ready, advance, budget_ms)
        self.policy.note(entries, chosen); elapsed = 1000.0 * (perf_counter() - started)
        report = _controller_report(chosen, stats, elapsed); self._record(report); return report

    def _prepare_controllers(self, selected, advance, started, budget_ms):
        deadline = started + max(0.0, float(budget_ms)) / 1000.0; chosen = []
        for row in selected:
            if chosen and perf_counter() >= deadline: break
            chosen.append(row)
            if _controller_run(row.session) is None and not row.session.done: advance(row.key)
        return tuple(chosen)

    def _execute_controllers(self, ready, advance, budget_ms):
        if len(ready) < 2:
            for row, _run in ready: advance(row.key)
            return _empty_controller_stats()
        stats = self.controller_executor.execute(tuple(run for _row, run in ready), budget_ms)
        for row, _run in ready: advance(row.key)
        return stats

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
        controllers = getattr(self.controller_executor, "stats", lambda: {})()
        return dict(values, **extra, **controllers)


def _batch_report(selected, stats, elapsed):
    return V3BatchReport(tuple(row.key for row in selected), stats["submitted"],
        stats["completed"], stats["workers"], stats["elapsed_ms"], elapsed)


def _controller_report(selected, stats, elapsed):
    return V3BatchReport(tuple(row.key for row in selected), stats["sessions"],
        stats["completed"], stats["workers"], stats["elapsed_ms"], elapsed, stats["trials"])


def _controller_run(session):
    core = getattr(session, "core_session", None)
    return None if core is None or getattr(core, "phase", "") != "NATIVE_SOLVE" else core.native_run


def _multi_session_enabled():
    raw = os.environ.get("AF_FIBER_V3_MULTI_SESSION", "0").strip().upper()
    if raw in {"0", "OFF", "FALSE"}: return False
    if raw in {"1", "ON", "TRUE"}: return True
    raise ValueError("AF_FIBER_V3_MULTI_SESSION must be 0 or 1")


def _empty_controller_stats():
    return {"sessions": 0, "completed": 0, "workers": 0, "elapsed_ms": 0.0, "trials": 0}


def _single_sweep_key(selected, sweeps):
    if len(sweeps) != 1: return None
    return next((row.key for row in selected
                 if getattr(row.session, "pending_native_sweep", None) is sweeps[0]), None)
