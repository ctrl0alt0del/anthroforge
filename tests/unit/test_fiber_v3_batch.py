import unittest
from unittest.mock import patch

from core.vcp.v3.batch import V3BatchCoordinator, V3OpenMpExecutor, V3WeightedSchedulingPolicy


class FakeSession:
    def __init__(self, sweep=None):
        self.done = False
        self.pending_native_sweep = sweep


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, sweeps):
        self.calls.append(tuple(sweeps))
        count = len(sweeps)
        return {"submitted": count, "completed": count, "workers": count,
                "elapsed_ms": float(count)}


class FakeControllerExecutor:
    def __init__(self): self.calls = []

    def execute(self, runs, budget_ms):
        self.calls.append((tuple(runs), budget_ms)); count = len(runs)
        return {"sessions": count, "completed": 0, "workers": min(4, count),
                "elapsed_ms": 2.0, "trials": count}


class FakeControllerSession:
    def __init__(self, run):
        self.done = False
        value = type("Run", (), {"done": False, "name": run})()
        self.core_session = type("Core", (), {"phase": "NATIVE_SOLVE", "native_run": value})()


def _legacy_step(coordinator, budget, advance):
    with patch.dict("os.environ", {"AF_FIBER_V3_MULTI_SESSION": "0"}):
        return coordinator.step(budget, advance)


class FiberV3BatchTests(unittest.TestCase):
    def test_coordinator_batches_independent_sessions(self):
        executor = FakeExecutor(); coordinator = V3BatchCoordinator(executor=executor,
            worker_count=lambda: 4)
        coordinator.add("a", FakeSession("sweep-a"), 8)
        coordinator.add("b", FakeSession("sweep-b"), 4)
        report = _legacy_step(coordinator, 12.0, lambda _key: None)
        self.assertEqual((report.selected, executor.calls), (("a", "b"), [("sweep-a", "sweep-b")]))
        self.assertEqual((report.submitted, report.completed, report.workers), (2, 2, 2))

    def test_coordinator_prepares_only_one_step_per_session(self):
        executor = FakeExecutor(); coordinator = V3BatchCoordinator(executor=executor,
            worker_count=lambda: 2); sessions = {key: FakeSession() for key in ("a", "b")}
        for key, session in sessions.items(): coordinator.add(key, session)
        calls = []
        def advance(key):
            calls.append(key); sessions[key].pending_native_sweep = f"sweep-{key}"
        _legacy_step(coordinator, 12.0, advance)
        self.assertEqual((calls, executor.calls), (["a", "b"], [("sweep-a", "sweep-b")]))

    def test_priority_aging_prevents_starvation(self):
        coordinator = V3BatchCoordinator(executor=FakeExecutor(), worker_count=lambda: 1)
        coordinator.add("selected", FakeSession("high"), 8)
        coordinator.add("background", FakeSession("low"), 1)
        chosen = [_legacy_step(coordinator, 12.0, lambda _key: None).selected[0] for _ in range(9)]
        self.assertIn("background", chosen)

    def test_remove_cancels_future_scheduling(self):
        executor = FakeExecutor(); coordinator = V3BatchCoordinator(executor=executor,
            worker_count=lambda: 2)
        coordinator.add("removed", FakeSession("old")); coordinator.remove("removed")
        report = _legacy_step(coordinator, 12.0, lambda _key: None)
        self.assertEqual((report.selected, executor.calls), ((), [()]))

    def test_single_sweep_waits_one_tick_for_batch_peer(self):
        executor = FakeExecutor(); coordinator = V3BatchCoordinator(executor=executor,
            worker_count=lambda: 2); first, second = FakeSession("a"), FakeSession()
        coordinator.add("first", first); coordinator.add("second", second)
        initial = _legacy_step(coordinator, 0.0, lambda _key: None)
        second.pending_native_sweep = "b"
        batched = _legacy_step(coordinator, 12.0, lambda _key: None)
        self.assertEqual((initial.submitted, batched.submitted), (0, 2))
        self.assertEqual(set(executor.calls[0]), {"a", "b"})

    def test_policy_uses_stable_ordinal_for_equal_priority(self):
        coordinator = V3BatchCoordinator(policy=V3WeightedSchedulingPolicy(),
            executor=FakeExecutor(), worker_count=lambda: 1)
        coordinator.add("first", FakeSession("a")); coordinator.add("second", FakeSession("b"))
        self.assertEqual(_legacy_step(coordinator, 12.0, lambda _key: None).selected, ("first",))

    def test_executor_disables_parallelism_for_tiny_jobs(self):
        tiny = {"submitted": 2, "completed": 2, "workers": 2, "elapsed_ms": 0.01}
        serial = dict(tiny, workers=1, elapsed_ms=0.02)
        executor = V3OpenMpExecutor(minimum_parallel_ms=0.25, qualification_batches=2)
        with patch("core.vcp.v3.batch.run_native_sweep_batch", return_value=tiny) as parallel, \
             patch("core.vcp.v3.batch.run_native_sweep_serial", return_value=serial) as fallback:
            executor.execute((1, 2)); executor.execute((1, 2)); executor.execute((1, 2))
        self.assertEqual((parallel.call_count, fallback.call_count), (2, 1))

    def test_multi_session_advances_controllers_in_one_native_call(self):
        executor = FakeControllerExecutor(); coordinator = V3BatchCoordinator(
            controller_executor=executor, worker_count=lambda: 4)
        sessions = {key: FakeControllerSession(key) for key in ("a", "b", "c")}
        for key, session in sessions.items(): coordinator.add(key, session)
        calls = []
        with patch.dict("os.environ", {"AF_FIBER_V3_MULTI_SESSION": "1"}):
            report = coordinator.step(12.0, calls.append)
        names = tuple(run.name for run in executor.calls[0][0])
        self.assertEqual((names, executor.calls[0][1]), (("a", "b", "c"), 12.0))
        self.assertEqual((report.submitted, report.workers, calls), (3, 3, ['a', 'b', 'c']))

    def test_multi_session_is_enabled_by_default(self):
        executor = FakeControllerExecutor(); coordinator = V3BatchCoordinator(
            controller_executor=executor, worker_count=lambda: 4)
        for key in ("a", "b"): coordinator.add(key, FakeControllerSession(key))
        with patch.dict("os.environ", {}, clear=True): report = coordinator.step(12.0, lambda _key: None)
        self.assertEqual((report.submitted, report.workers), (2, 2))

    def test_invalid_multi_session_environment_fails_configuration(self):
        coordinator = V3BatchCoordinator(executor=FakeExecutor())
        with patch.dict("os.environ", {"AF_FIBER_V3_MULTI_SESSION": "AUTO"}):
            with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
                coordinator.step(12.0, lambda _key: None)


if __name__ == "__main__":
    unittest.main()
