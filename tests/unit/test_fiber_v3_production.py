import subprocess
import sys
import unittest
from time import sleep
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace
from importlib.util import find_spec

import numpy as np

from core.vcp.v2.collision import collision_backend_status
from core.vcp.v2.contracts import V2Topology
from core.vcp.v3.manifest import V3_ACCEPTED_REFERENCE, V3_REJECTED_MODULES
from core.vcp.v3.policy import V3_PRODUCTION_POLICY, V3ShortcutMode, accepted_v3_request
from core.vcp.v3.production import (V3_PRODUCTION_VERSION, begin_v3, solve_v3,
                                    solve_v3_controller)
from core.vcp.v3.native_controller import (_prepare_report_install, poll_native_controllers,
                                            shutdown_native_async_controllers)
from tests.unit.test_fiber_v2_planner import _anchors, _angle_points, _box, _request, _sphere


def _bent_request(cap=24):
    request = _request(_anchors(((0, 0, 0), (1, 1, 0), (2, 0, 0))), count=33)
    settings = replace(request.settings, max_accepted_steps=cap, curvature_weight=0.75)
    return replace(request, settings=settings)


def _cyclic_request(cap=24, count=32):
    points = ((1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0))
    request = _request(_anchors(points), count=count, topology=V2Topology.CYCLIC)
    return replace(request, settings=replace(request.settings, max_accepted_steps=cap))


class _SpanFixture:
    def __init__(self, points):
        self.state = SimpleNamespace(points=points, owner_span_override=.01)

    @property
    def points(self):
        return self.state.points


def _owner_span_fixture():
    collision = SimpleNamespace(collision_radius=.01)
    tolerances = SimpleNamespace(clearance_slack=.001)
    request = SimpleNamespace(collision_policy=collision, tolerances=tolerances)
    points = (np.asarray(((0, 0, 0), (.2, 0, 0), (.3, 0, 0))),
              np.asarray(((.3, 0, 0), (1, 0, 0))))
    spans = tuple(_SpanFixture(row * .1) for row in points)
    report = SimpleNamespace(spans=tuple(SimpleNamespace(points=row) for row in points))
    return SimpleNamespace(spans=spans, request=request, pins=(0, 2, 3), cyclic=False), report


def _native_ready(request):
    session = begin_v3(request, use_planner=False)
    while session.phase != "NATIVE_SOLVE": session.step()
    return session


def _wait_async(sessions):
    for _index in range(2000):
        runs = tuple(row.native_run for row in sessions if row.native_run is not None)
        poll_native_controllers(runs)
        if all(run.done for run in runs): return
        sleep(.001)
    raise AssertionError("asynchronous native controllers did not finish")


class FiberV3ProductionTests(unittest.TestCase):
    def test_final_native_points_refresh_shared_owner_span(self):
        session, report = _owner_span_fixture(); _prepare_report_install(session, report)
        self.assertEqual([row.state.owner_span_override for row in session.spans], [.7, .7])

    def test_cyclic_controller_is_one_global_state(self):
        session = begin_v3(_cyclic_request(8), use_planner=False)
        while session.phase != "NATIVE_SOLVE": session.step()
        self.assertTrue(session.cyclic); self.assertEqual(len(session.spans), 1)
        state = session.spans[0].state
        self.assertEqual((len(state.points), len(state.pin_indices)), (33, 5))
        np.testing.assert_array_equal(state.points[0], state.points[-1]); session.cancel()

    def test_cyclic_result_has_exact_count_and_closing_edge(self):
        package = solve_v3(_cyclic_request(12), use_planner=False)
        points = np.asarray(package.result.points)
        self.assertEqual((len(points), package.result.validated), (32, True))
        self.assertFalse(np.array_equal(points[0], points[-1]))
        lengths = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
        self.assertAlmostEqual(package.result.diagnostics.true_length, float(lengths.sum()))

    def test_cyclic_native_and_python_controllers_match(self):
        request = _cyclic_request(12)
        python = solve_v3(request, use_planner=False, native_controller=False)
        native = solve_v3(request, use_planner=False, native_controller=True)
        np.testing.assert_allclose(native.result.points, python.result.points, atol=3e-14, rtol=0)
        self.assertEqual(native.result.termination, python.result.termination)

    def test_cyclic_warm_seed_stays_closed_internally(self):
        request = _cyclic_request(8); warm = np.asarray(solve_v3(request).result.points)
        session = begin_v3(replace(request, warm_seed=tuple(map(tuple, warm))))
        while session.phase != "NATIVE_SOLVE": session.step()
        np.testing.assert_array_equal(session.spans[0].state.points[0],
                                      session.spans[0].state.points[-1])
        session.cancel()

    def test_cyclic_native_owner_contacts_cover_every_hard_anchor(self):
        anchors = _anchors(_angle_points((0, np.pi / 2, np.pi, 3 * np.pi / 2)), "SPHERE")
        request = _request(anchors, (_sphere(),), 32, .02, V2Topology.CYCLIC)
        request = replace(request, settings=replace(request.settings, max_accepted_steps=40))
        package = solve_v3(request, native_controller=True)
        self.assertTrue(package.result.validated)
        points = np.asarray(package.result.points)
        for anchor in anchors:
            self.assertLess(float(np.min(np.linalg.norm(points - anchor.point, axis=1))), 1.0e-12)

    def test_cyclic_unrelated_blocked_pin_keeps_precise_termination(self):
        anchors = _anchors(((0, 0, 0), (1, 0, 0), (0, 1, 0)))
        request = _request(anchors, (_box(),), 24, .02, V2Topology.CYCLIC)
        package = solve_v3(request, use_planner=False)
        self.assertEqual(package.result.termination.value, "INVALID_CONFIGURATION")
        self.assertFalse(package.result.validated)

    def test_native_session_matches_reference_driver(self):
        request = _bent_request(20)
        reference = solve_v3(request, use_planner=False, native_session=False, native_controller=False)
        fused = solve_v3(request, use_planner=False, native_session=True, native_controller=False)
        np.testing.assert_array_equal(fused.result.points, reference.result.points)
        self.assertEqual(fused.result.termination, reference.result.termination)
        self.assertEqual(fused.result.diagnostics.accepted_steps,
                         reference.result.diagnostics.accepted_steps)

    def test_native_controller_matches_clear_reference(self):
        request = _bent_request(20)
        expected = solve_v3(request, use_planner=False, native_controller=False)
        actual = solve_v3_controller(request, use_planner=False)
        np.testing.assert_allclose(actual.result.points, expected.result.points, atol=3e-14, rtol=0)
        self.assertEqual(actual.result.termination, expected.result.termination)

    def test_native_controller_is_default(self):
        request = _bent_request(8)
        package = solve_v3(request, use_planner=False)
        self.assertEqual(package.result.diagnostics.controller, "NATIVE")

    def test_python_controller_environment_fallback_is_explicit(self):
        request = _bent_request(8)
        with patch.dict("os.environ", {"AF_FIBER_V3_NATIVE_CONTROLLER": "0"}):
            package = solve_v3(request, use_planner=False)
        self.assertEqual(package.result.diagnostics.controller, "PYTHON")

    def test_explicit_native_controller_choice_overrides_environment(self):
        request = _bent_request(8)
        with patch.dict("os.environ", {"AF_FIBER_V3_NATIVE_CONTROLLER": "1"}):
            session = begin_v3(request, use_planner=False, native_controller=False)
        self.assertFalse(session.native_controller)

    def test_invalid_native_controller_environment_fails_configuration(self):
        with patch.dict("os.environ", {"AF_FIBER_V3_NATIVE_CONTROLLER": "AUTO"}):
            with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
                begin_v3(_bent_request(8), use_planner=False)

    def test_completed_session_releases_native_handle(self):
        session = begin_v3(_bent_request(8), use_planner=False, native_session=True)
        while not session.done: session.step()
        self.assertTrue(all(row.state.native_session is None for row in session.spans))

    def test_cancelled_session_releases_native_handle(self):
        session = begin_v3(_bent_request(20), use_planner=False, native_session=True)
        for _index in range(12):
            session.step()
            if any(row.state.native_session is not None for row in session.spans): break
        self.assertTrue(any(row.state.native_session is not None for row in session.spans))
        session.cancel()
        self.assertTrue(session.done)
        self.assertTrue(all(row.state.native_session is None for row in session.spans))

    def test_native_controller_cancellation_releases_coordinator(self):
        session = begin_v3(_bent_request(20), use_planner=False)
        while session.phase != "NATIVE_SOLVE": session.step()
        self.assertIsNotNone(session.native_run.handle); session.cancel()
        self.assertIsNone(session.native_run)
        self.assertTrue(all(row.state.native_session is None for row in session.spans))

    def test_parallel_native_sessions_do_not_share_state(self):
        first = begin_v3(_bent_request(8), use_planner=False, native_session=True)
        second = begin_v3(_bent_request(12), use_planner=False, native_session=True)
        while not first.done or not second.done:
            if not first.done: first.step()
            if not second.done: second.step()
        expected_first = solve_v3(_bent_request(8), use_planner=False)
        expected_second = solve_v3(_bent_request(12), use_planner=False)
        self.assertEqual(first.package.result.points, expected_first.result.points)
        self.assertEqual(second.package.result.points, expected_second.result.points)

    def test_async_native_coordinator_finishes_independent_sessions(self):
        sessions = (_native_ready(_bent_request(8)), _native_ready(_bent_request(12)))
        try:
            _wait_async(sessions)
            for session in sessions: session.step()
            self.assertTrue(all(session.done and session.package.result.validated for session in sessions))
        finally:
            for session in sessions:
                if not session.done: session.cancel()
            shutdown_native_async_controllers()

    def test_async_native_coordinator_cancels_before_buffer_release(self):
        session = _native_ready(_bent_request(180))
        try:
            poll_native_controllers((session.native_run,)); session.cancel()
            self.assertTrue(session.done); self.assertIsNone(session.native_run)
        finally:
            if not session.done: session.cancel()
            shutdown_native_async_controllers()

    def test_native_controller_keeps_python_warm_seed_selection(self):
        request = _bent_request(8)
        warm = tuple((index / 32.0 * 2.0, 0.2, 0.0) for index in range(33))
        session = begin_v3(replace(request, warm_seed=warm), use_planner=False)
        while session.phase != "SPANS": session.step()
        expected = np.asarray(warm); expected[[0, 16, 32]] = [row.point for row in request.anchors]
        np.testing.assert_array_equal(session.seed, expected)

    def test_warm_seed_skips_planner_and_takes_precedence(self):
        request = _bent_request(8)
        warm = tuple((index / 16.0, 0.2, 0.0) for index in range(33))
        with patch("core.vcp.v3.solver.plan_reference_v43") as planner:
            session = begin_v3(replace(request, warm_seed=warm), use_planner=True)
            while session.phase != "SPANS": session.step()
        planner.assert_not_called()
        np.testing.assert_allclose(session.seed[1], warm[1])

    def test_native_controller_keeps_hard_midpoint_spans(self):
        session = begin_v3(_bent_request(8), use_planner=False)
        while session.phase != "NATIVE_SOLVE": session.step()
        self.assertEqual(len(session.spans), 2)
        self.assertEqual(tuple(session.pins), (0, 16, 32))
        session.cancel()

    def test_manifest_freezes_accepted_reference(self):
        self.assertEqual(V3_ACCEPTED_REFERENCE["name"], "REG_ADAPTIVE_SPACING")
        self.assertEqual(V3_ACCEPTED_REFERENCE["global_accepted_cap"], 180)

    def test_request_forces_accepted_objective(self):
        request = accepted_v3_request(_bent_request())
        self.assertEqual(request.settings.curvature_weight, 0.0)
        self.assertAlmostEqual(request.settings.fidelity_weight, 0.01)

    def test_v3_is_deterministic_at_fixed_cap(self):
        request = _bent_request(20)
        first, second = solve_v3(request), solve_v3(request)
        self.assertEqual(first.result.points, second.result.points)
        self.assertEqual(first.result.termination, second.result.termination)

    def test_result_reports_v3_identity_and_zero_curvature(self):
        package = solve_v3(_bent_request(8), use_planner=False)
        self.assertEqual(package.result.engine_version, V3_PRODUCTION_VERSION)
        self.assertEqual(package.result.diagnostics.effective_curvature_weight, 0.0)
        self.assertEqual(package.result.diagnostics.native_worker_threads,
                         collision_backend_status().worker_threads)

    def test_checkpoint_continues_to_terminal_result(self):
        session = begin_v3(_bent_request(12), checkpoint_steps=2, use_planner=False)
        while not session.done and not session.checkpoint_ready: session.step()
        while not session.done: session.step()
        self.assertTrue(session.package.result.validated)
        self.assertLessEqual(session.package.result.diagnostics.accepted_steps, 12)

    def test_resumable_and_synchronous_native_results_match(self):
        request = _bent_request(20); session = begin_v3(request, use_planner=False)
        while not session.done: session.step()
        synchronous = solve_v3(request, use_planner=False)
        self.assertEqual(session.package.result.points, synchronous.result.points)
        self.assertEqual(session.package.result.termination, synchronous.result.termination)

    def test_missing_native_controller_never_falls_back_to_python(self):
        session = begin_v3(_bent_request(8), use_planner=False)
        with patch("core.vcp.v3.native_controller.cn.native_controller_status", return_value=False):
            while not session.done: session.step()
        self.assertEqual(session.package.result.termination.value, "BACKEND_UNAVAILABLE")
        self.assertFalse(session.package.result.validated)

    def test_shadow_and_off_have_identical_solver_output(self):
        request = _bent_request(12)
        off_policy = replace(V3_PRODUCTION_POLICY, shortcut_mode=V3ShortcutMode.OFF)
        shadow_policy = replace(V3_PRODUCTION_POLICY, shortcut_mode=V3ShortcutMode.SHADOW)
        off = solve_v3(request, policy=off_policy)
        shadow = solve_v3(request, policy=shadow_policy)
        self.assertTrue(np.array_equal(off.result.points, shadow.result.points))
        self.assertEqual(off.result.termination, shadow.result.termination)

    def test_production_import_excludes_rejected_modules(self):
        output = subprocess.check_output([sys.executable, "-c", _import_probe()], text=True)
        self.assertEqual(output.strip(), "")

    def test_rejected_solver_modules_were_removed(self):
        for name in V3_REJECTED_MODULES:
            self.assertIsNone(find_spec(_rejected_import(name)), name)


def _import_probe():
    rejected = repr(tuple(V3_REJECTED_MODULES))
    return ("import sys; import core.vcp.v3.production; "
            f"r={rejected}; print('\\n'.join(n for n in sys.modules if any(n.endswith(x) for x in r)))")


def _rejected_import(name):
    prefix = "core.vcp." if name.startswith("v3_") else "core.vcp.v2."
    return prefix + name


if __name__ == "__main__":
    unittest.main()
