"""Isolated full-session worker-pool experiment for pure-data V3 solves."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import get_ident
from time import perf_counter


@dataclass(frozen=True)
class V3SessionPoolReport:
    elapsed_ms: float
    steps: int
    tasks: int
    workers: int
    thread_ids: tuple
    session_threads: tuple


class V3SessionPoolExperiment:
    def __init__(self, workers=4, quantum=4):
        self.workers = max(1, int(workers))
        self.quantum = max(1, int(quantum))
        self.steps = self.tasks = 0
        self.threads = set()
        self.session_threads = {}

    def run(self, sessions):
        rows = tuple(sessions); started = perf_counter()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            self._drain(pool, rows)
        elapsed = 1000.0 * (perf_counter() - started)
        return self._report(elapsed, rows)

    def _drain(self, pool, sessions):
        active = {pool.submit(_advance_quantum, row, self.quantum): row for row in sessions if not row.done}
        try:
            while active:
                done, _pending = wait(active, return_when=FIRST_COMPLETED)
                for future in done: self._complete(pool, active, future)
        except Exception:
            _cancel_sessions(sessions); raise

    def _complete(self, pool, active, future):
        session = active.pop(future); steps, thread_id = future.result()
        self.steps += steps; self.tasks += 1; self.threads.add(thread_id)
        self.session_threads.setdefault(id(session), set()).add(thread_id)
        if not session.done: active[pool.submit(_advance_quantum, session, self.quantum)] = session

    def _report(self, elapsed, sessions):
        ownership = tuple(tuple(sorted(self.session_threads.get(id(row), ()))) for row in sessions)
        return V3SessionPoolReport(elapsed, self.steps, self.tasks, self.workers,
                                   tuple(sorted(self.threads)), ownership)


def run_v3_sessions_serial(sessions, quantum=4):
    rows = tuple(sessions); started = perf_counter(); steps = tasks = 0
    while any(not row.done for row in rows):
        for row in rows:
            if row.done: continue
            count, _thread = _advance_quantum(row, quantum); steps += count; tasks += 1
    elapsed = 1000.0 * (perf_counter() - started)
    return V3SessionPoolReport(elapsed, steps, tasks, 1, (get_ident(),),
                               tuple((get_ident(),) for _row in rows))


def _advance_quantum(session, quantum):
    steps = 0
    while steps < int(quantum) and not session.done:
        session.step(); steps += 1
    return steps, get_ident()


def _cancel_sessions(sessions):
    for session in sessions:
        cancel = getattr(session, "cancel", None)
        if callable(cancel): cancel()
