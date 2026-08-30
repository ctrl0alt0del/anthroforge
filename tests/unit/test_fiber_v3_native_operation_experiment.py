import unittest

import numpy as np

from core.vcp.v2.collision import clear_native_collision_world_cache, clear_triangle_snapshot_cache
from core.vcp.v2.collision_native import native_status
from core.vcp.v2.structural import clear_structural_cache
from core.vcp.v3.native_operation_experiment import (EXPERIMENT_DLL,
    V3NativeOperationExperiment, _MeasureOperation, _StructuralOperation, _SweepOperation,
    V3NativeCoordinatorLiveExperiment, V3PersistentNativeCoordinator,
    execute_native_coordinator, execute_native_operations, experimental_backend)
from core.vcp.v3.production import begin_v3
from tests.unit.test_fiber_v2_solver import _box_request
from tests.unit.test_fiber_v3_production import _bent_request


def _clear():
    clear_native_collision_world_cache(); clear_triangle_snapshot_cache(); clear_structural_cache()


def _direct(request):
    session = begin_v3(request, use_planner=False, native_session=True, native_controller=False)
    while not session.done: session.step()
    return session


def _coordinated(requests):
    sessions = tuple(begin_v3(row, use_planner=False, native_session=True,
                             native_controller=False) for row in requests)
    report = V3NativeOperationExperiment().run(sessions)
    return sessions, report


def _native_state(request):
    session = begin_v3(request, use_planner=False, native_session=True, native_controller=False)
    while not session.done:
        session.step()
        state = next((row.state for row in session.spans if row.state is not None), None)
        native = None if state is None else state.native_session
        if native is not None and native.snapshot_attached: return session, state
    raise RuntimeError("V3 native state did not initialize")


def _operations(state):
    count = len(state.points); span = max(state.request.collision_policy.collision_radius * 3.0, 1.0e-3)
    radius = state.request.collision_policy.collision_radius; slack = state.request.tolerances.clearance_slack
    measure = _MeasureOperation(state.native_session, state.points, span, radius + max(4 * slack, .25 * radius),
                                max(0.0, radius - slack))
    bands = (np.full(count, 2.0), np.zeros(count), np.zeros(count)); rhs = np.asarray(state.points).copy()
    contact = ((0, .5, (0.0, 1.0, 0.0)),); pins = (0, count - 1)
    structural = _StructuralOperation(state.native_session, bands, rhs, contact, pins, rhs[list(pins)])
    target = np.asarray(state.points).copy(); target[1:-1, 2] += 1.0e-5
    sweep = _SweepOperation(state.native_session, state.points, target, max(0.0, radius - slack), 1.0e-5, 262143)
    return measure, structural, sweep


def _operation_bytes(operations):
    measure, structural, sweep = operations; arrays = measure.references[2]
    rows = bytes(measure.references[1]); validation = b"".join(np.asarray(row).tobytes() for row in arrays)
    block = structural.references[-2].tobytes() + structural.references[-1].tobytes()
    result = sweep.payload.result; sweep_row = (result.safe, result.valid, result.tested, sweep.payload.edge, sweep.payload.face)
    return rows, validation, block, sweep_row


class FiberV3NativeOperationExperimentTests(unittest.TestCase):
    def test_experimental_backend_is_isolated_and_available(self):
        self.assertNotEqual(EXPERIMENT_DLL.name, "af_fiber_ccd_v3.dll")
        available, version, message = native_status(EXPERIMENT_DLL)
        self.assertTrue(available, message); self.assertIn("4194303", version)

    def test_cpp_coordinator_preserves_indexed_kernel_outputs(self):
        with experimental_backend():
            session, state = _native_state(_box_request()); operations = _operations(state)
            for operation in operations: execute_native_operations((operation,))
            expected = _operation_bytes(operations); report = execute_native_coordinator(operations)
            actual = _operation_bytes(operations); session.cancel()
        self.assertEqual(actual, expected); self.assertTrue(report.deterministic)
        self.assertEqual((report.streams, report.structural_jobs), (1, 1))
        self.assertGreater(report.contact_jobs + report.ccd_broad_jobs, 0)

    def test_persistent_cpp_coordinator_advances_bounded_slices(self):
        with experimental_backend():
            session, state = _native_state(_box_request()); operations = _operations(state)
            coordinator = V3PersistentNativeCoordinator(operations); reports, done = [], False
            try:
                while not done:
                    report, done = coordinator.step(0.0); reports.append(report)
            finally: coordinator.close(); session.cancel()
        self.assertEqual([row.operations for row in reports], [1, 2, 3])
        self.assertTrue(all(operation.done for operation in operations))

    def test_atomic_executor_matches_direct_collision_solve_exactly(self):
        with experimental_backend():
            expected = _direct(_box_request()); _clear()
            sessions, report = _coordinated((_box_request(),))
        actual = sessions[0]
        np.testing.assert_array_equal(actual.package.result.points, expected.package.result.points)
        self.assertEqual(actual.package.result.termination, expected.package.result.termination)
        self.assertEqual(report.jobs, 0)

    def test_four_fibers_share_workers_without_changing_results(self):
        requests = (_bent_request(24), _box_request(), _bent_request(24), _box_request())
        with experimental_backend():
            expected = tuple(_direct(row).package.result for row in requests); _clear()
            sessions, report = _coordinated(requests)
        for result, session in zip(expected, sessions):
            np.testing.assert_array_equal(session.package.result.points, result.points)
            self.assertEqual(session.package.result.termination, result.termination)
        self.assertGreater(report.jobs, 0); self.assertGreaterEqual(report.workers_used, 1)

    def test_cpp_coordinator_replays_real_solver_trace_without_python_operations(self):
        requests = (_bent_request(8), _box_request())
        with experimental_backend():
            sessions = tuple(begin_v3(row, use_planner=False, native_session=True,
                                     native_controller=False) for row in requests)
            experiment = V3NativeOperationExperiment(retain_trace=True)
            experiment.run(sessions)
            try: replay = experiment.replay()
            finally: experiment.release_trace()
        self.assertEqual(replay.operations, replay.exact_operations)
        self.assertEqual((replay.contact_mismatches, replay.structural_mismatches,
                          replay.sweep_mismatches), (0, 0, 0))
        self.assertGreater(replay.coordinator.contact_jobs + replay.coordinator.ccd_pair_jobs, 0)

    def test_live_coordinator_path_stays_valid_and_matches_reference(self):
        requests = (_bent_request(12), _box_request())
        with experimental_backend():
            expected = tuple(_direct(row).package.result for row in requests); _clear()
            sessions = tuple(begin_v3(row, use_planner=False, native_session=True,
                                     native_controller=False) for row in requests)
            V3NativeCoordinatorLiveExperiment().run(sessions)
        for result, session in zip(expected, sessions):
            self.assertTrue(session.package.result.validated)
            np.testing.assert_array_equal(session.package.result.points, result.points)


if __name__ == "__main__":
    unittest.main()
