import unittest
from types import SimpleNamespace

import numpy as np

from core.vcp.v2.acceleration import AndersonHistory
from core.vcp.v2.collision import build_native_collision_world
from core.vcp.v2.collision_native import (native_contact_block_solve,
                                          native_structural_contact_responses)
from core.vcp.v2.contact_core import (V2Contact, _merge_contacts,
                                      begin_contact_core, solve_contact_core)
from core.vcp.v2.contracts import V2ColliderSnapshot
from core.vcp.v2.structural import (_base_bands, _static_settings, assemble_normal_matrix,
                                    smooth_coefficients)
from core.vcp.v2.subfiber_sqp import (_span_settings, solve_subfiber_sqp,
                                      solve_subfiber_sqp_fixed)
from core.vcp.v2.trust_sqp import update_trust_radius
from tests.unit.test_fiber_v2_solver import _box_request
from tests.unit.test_fiber_v2_planner import _anchors, _request


def _contact_state(request, contact):
    return SimpleNamespace(request=request, contacts={contact.key: contact}, injected=0,
                           retired=0, mu=100.0, energy_streak=3,
                           acceleration_enabled=False)


def _assembled_dense(request, current, contacts, mu):
    scalar = assemble_normal_matrix(len(current), _static_settings(request.settings))
    matrix = np.kron(scalar, np.eye(3)); rhs = request.settings.fidelity_weight * current.reshape(-1)
    for edge, factor, normal, gap, multiplier in contacts:
        jacobian = np.zeros(3 * len(current)); normal = np.asarray(normal)
        jacobian[3 * edge:3 * edge + 3] = (1.0 - factor) * normal
        jacobian[3 * edge + 3:3 * edge + 6] = factor * normal
        active = max(0.0, multiplier - mu * gap)
        if active <= 0.0: continue
        matrix += mu * np.outer(jacobian, jacobian)
        rhs += mu * jacobian * float(jacobian @ current.reshape(-1)) + active * jacobian
    return matrix, rhs


def _dense_with_pins(matrix, rhs, pins, targets):
    count = len(rhs) // 3; fixed = np.asarray([3 * pin + axis for pin in pins for axis in range(3)])
    free = np.setdiff1d(np.arange(3 * count), fixed); target = np.asarray(targets).reshape(-1)
    solved = np.zeros(3 * count); solved[fixed] = target
    solved[free] = np.linalg.solve(matrix[np.ix_(free, free)], rhs[free] - matrix[np.ix_(free, fixed)] @ target)
    return solved.reshape((-1, 3))


def _dense_response(matrix, jacobian, pins):
    count = len(jacobian); fixed = np.asarray([3 * pin + axis for pin in pins for axis in range(3)])
    free = np.setdiff1d(np.arange(3 * count), fixed); output = np.zeros(3 * count)
    output[free] = np.linalg.solve(matrix[np.ix_(free, free)], jacobian.reshape(-1)[free])
    return output.reshape((-1, 3))


class FiberV2ContactCoreTests(unittest.TestCase):
    def test_unmatched_ccd_limiter_retires_immediately(self):
        limiter = V2Contact(8, .63, "C", 4, "LIMITING", (0, 1, 0), 0.0, multiplier=274.0)
        state = _contact_state(_box_request(), limiter)
        self.assertEqual(_merge_contacts(state, ()), {})
        self.assertEqual((state.retired, state.energy_streak), (1, 0))

    def test_ccd_limiter_migrates_to_current_surface_contact(self):
        limiter = V2Contact(8, .63, "C", 4, "LIMITING", (0, 1, 0), 0.0, multiplier=274.0)
        fresh = V2Contact(8, .61, "C", 7, "DISTANCE", (0, 1, 0), .0001)
        output = _merge_contacts(_contact_state(_box_request(), limiter), (fresh,))
        self.assertEqual(tuple(output.values())[0].feature_id, "DISTANCE")
        self.assertEqual(tuple(output.values())[0].multiplier, 274.0)

    def test_anderson_accelerates_stable_affine_fixed_point(self):
        base = np.zeros(3); fast = base.copy(); history = AndersonHistory(4)
        for _index in range(6): base = .8 * base + np.ones(3)
        for _index in range(6):
            mapped = .8 * fast + np.ones(3)
            fast, _used = history.propose(fast, mapped, ("stable",))
        self.assertLess(np.linalg.norm(fast - 5.0), np.linalg.norm(base - 5.0))

    def test_anderson_restarts_when_contact_signature_changes(self):
        history = AndersonHistory(4); point = np.zeros(3)
        for _index in range(3):
            mapped = .5 * point + 1.0; point, _used = history.propose(point, mapped, ("A",))
        _value, used = history.propose(point, .5 * point + 1.0, ("B",))
        self.assertFalse(used); self.assertEqual(len(history.points), 1)

    def test_native_contact_block_matches_dense_reference(self):
        request = _box_request(); count = request.settings.node_count
        current = np.linspace((-1, .1, 0), (1, .1, 0), count); mu = 37.0
        contacts = ((8, .2, (0, 1, 0), -.04, 2.0), (12, .7, (1, 0, 0), .01, 1.0))
        pins, targets = (0, count - 1), (current[0], current[-1])
        bands = _base_bands(count, _static_settings(request.settings)); rhs = request.settings.fidelity_weight * current
        solved, _trace = native_contact_block_solve(bands, rhs, current, contacts, pins, targets, mu)
        matrix, dense_rhs = _assembled_dense(request, current, contacts, mu)
        np.testing.assert_allclose(solved, _dense_with_pins(matrix, dense_rhs, pins, targets), atol=2.0e-12)

    def test_inactive_contact_has_zero_matrix_contribution(self):
        request = _box_request(); count = request.settings.node_count
        current = np.linspace((-1, .1, 0), (1, .1, 0), count); mu = 37.0
        contacts = ((8, .2, (0, 1, 0), .04, 0.0),)
        pins, targets = (0, count - 1), (current[0], current[-1])
        bands = _base_bands(count, _static_settings(request.settings)); rhs = request.settings.fidelity_weight * current
        solved, _trace = native_contact_block_solve(bands, rhs, current, contacts, pins, targets, mu)
        matrix, dense_rhs = _assembled_dense(request, current, contacts, mu)
        np.testing.assert_allclose(solved, _dense_with_pins(matrix, dense_rhs, pins, targets), atol=2.0e-12)

    def test_native_structural_responses_match_dense_reference(self):
        request = _box_request(); count = request.settings.node_count
        reference = np.linspace((-1, .2, 0), (1, .2, 0), count); pins = (0, count - 1)
        targets = (reference[0], reference[-1]); rows = ((8, .2, (0, 1, 0)), (12, .7, (1, 0, 0)))
        bands = _base_bands(count, _static_settings(request.settings)); rhs = request.settings.fidelity_weight * reference
        base, responses, _trace = native_structural_contact_responses(bands, rhs, rows, pins, targets)
        matrix = np.kron(assemble_normal_matrix(count, _static_settings(request.settings)), np.eye(3))
        np.testing.assert_allclose(base, _dense_with_pins(matrix, rhs.reshape(-1), pins, targets), atol=2e-12)
        for response, row in zip(responses, rows):
            jacobian = np.zeros_like(reference); jacobian[row[0]] = (1.0 - row[1]) * np.asarray(row[2])
            jacobian[row[0] + 1] = row[1] * np.asarray(row[2])
            np.testing.assert_allclose(response, _dense_response(matrix, jacobian, pins), atol=2e-12)

    def test_filter_trust_radius_uses_model_agreement(self):
        self.assertEqual(update_trust_radius(1.0, .01, 4.0, -.2, False, True), .25)
        self.assertEqual(update_trust_radius(1.0, .01, 4.0, .8, True, True), 2.0)
        self.assertEqual(update_trust_radius(1.0, .01, 4.0, .5, True, True), 1.0)

    def test_native_all_contact_query_keeps_adjacent_faces(self):
        collider = V2ColliderSnapshot("C", "BODY", ((-2, -2, 0), (2, -2, 0),
                                      (2, 2, 0), (-2, 2, 0)), ((0, 1, 2), (0, 2, 3)))
        world = build_native_collision_world((collider,)); points = np.asarray(((-1, 0, .1), (1, 0, .1)))
        result = world.contact_pairs(points, ((0, 1),), (("", ""),), 0.0, .2)
        self.assertEqual(len(result.pairs), 2)
        self.assertEqual({row.face for row in result.pairs}, {0, 1})

    def test_intersecting_direct_box_seed_reaches_safe_result_without_planner(self):
        request = _box_request(); result = solve_contact_core(request, use_planner=False)
        self.assertTrue(result.result.validated, result.result.message)
        self.assertTrue(result.result.diagnostics.feasibility_reached_from_invalid)
        self.assertLessEqual(result.result.diagnostics.max_constraint_violation,
                             request.tolerances.clearance_slack)
        self.assertEqual((result.result.points[0], result.result.points[-1]),
                         (request.anchors[0].point, request.anchors[-1].point))

    def test_accelerated_intersecting_seed_remains_independently_valid(self):
        request = _box_request()
        package = solve_contact_core(request, use_planner=False, use_acceleration=True)
        self.assertTrue(package.result.validated, package.result.message)
        self.assertLessEqual(package.result.diagnostics.max_constraint_violation,
                              request.tolerances.clearance_slack)

    def test_filter_sqp_intersecting_seed_converges_with_fewer_rejections(self):
        request = _box_request(); baseline = solve_contact_core(request, use_planner=False)
        package = solve_contact_core(request, use_planner=False, use_filter_sqp=True)
        self.assertTrue(package.result.validated, package.result.message)
        self.assertEqual(package.result.termination.value, "CONVERGED")
        self.assertLess(package.result.diagnostics.rejected_steps,
                        baseline.result.diagnostics.rejected_steps)

    def test_subfiber_sqp_preserves_authored_hard_kink(self):
        anchors = _anchors(((0, 0, 0), (1, 1, 0), (2, 0, 0)))
        package = solve_subfiber_sqp(_request(anchors, count=33), use_planner=False)
        points = np.asarray(package.result.points); middle = package.trace.spans[0].last_node
        self.assertTrue(package.result.validated, package.result.message)
        np.testing.assert_allclose(points[middle], anchors[1].point, atol=1e-12)
        np.testing.assert_allclose(points[:middle + 1, 0], points[:middle + 1, 1], atol=1e-10)
        np.testing.assert_allclose(points[middle:, 0] + points[middle:, 1], 2.0, atol=1e-10)

    def test_subfiber_sqp_advances_spans_in_round_robin(self):
        anchors = _anchors(((0, 0, 0), (.5, .2, 0), (1, 0, 0), (1.5, .3, 0)))
        package = solve_subfiber_sqp(_request(anchors, count=40), use_planner=False)
        self.assertEqual(len(package.trace.spans), 3)
        self.assertEqual(len(package.result.points), 40)
        self.assertGreaterEqual(package.trace.outer_rounds,
                                max(span.completed_round for span in package.trace.spans))

    def test_fixed_subfiber_preserves_global_structural_coefficients(self):
        request = _request(_anchors(((0, 0, 0), (1, 1, 0), (2, 0, 0))), count=64)
        global_values = smooth_coefficients(64, _static_settings(request.settings))
        local = _span_settings(request.settings, 13, True)
        local_values = smooth_coefficients(13, _static_settings(local))
        np.testing.assert_allclose(local_values[1:], global_values[1:], rtol=1e-14)

    def test_fixed_subfiber_removes_only_cross_pin_bend_row(self):
        request = _request(_anchors(((0, 0, 0), (1, 1, 0), (2, 0, 0))), count=9)
        static = _static_settings(request.settings); expected = assemble_normal_matrix(9, static)
        bend = smooth_coefficients(9, static)[2]; stencil = np.zeros(9)
        stencil[3:6] = (1, -2, 1); expected -= bend * np.outer(stencil, stencil)
        split = np.zeros((9, 9))
        for indices in (np.arange(5), np.arange(4, 9)):
            local = _static_settings(_span_settings(request.settings, 5, True))
            split[np.ix_(indices, indices)] += assemble_normal_matrix(5, local)
        free = (1, 2, 3, 5, 6, 7)
        np.testing.assert_allclose(split[np.ix_(free, free)], expected[np.ix_(free, free)])

    def test_fixed_subfiber_uses_one_global_accepted_step_cap(self):
        anchors = _anchors(((0, 0, 0), (.5, .2, 0), (1, 0, 0), (1.5, .3, 0)))
        request = _request(anchors, count=40)
        package = solve_subfiber_sqp_fixed(request, use_planner=False)
        self.assertLessEqual(package.result.diagnostics.accepted_steps,
                             request.settings.max_accepted_steps + len(package.trace.spans) - 1)
        self.assertEqual(len(package.result.points), request.settings.node_count)

    def test_resumable_session_matches_synchronous_result(self):
        request = _box_request(); expected = solve_contact_core(request, use_planner=False)
        session = begin_contact_core(request, use_planner=False)
        while not session.done: session.step()
        self.assertEqual(session.package.result.points, expected.result.points)
        self.assertEqual(session.package.result.termination, expected.result.termination)
        self.assertEqual(session.package.result.validated, expected.result.validated)

    def test_invalid_seed_is_exposed_only_as_private_working_state(self):
        session = begin_contact_core(_box_request(), use_planner=False)
        self.assertTrue(session.infeasible)
        self.assertFalse(session.done)
        self.assertGreater(len(session.points), 2)


if __name__ == "__main__":
    unittest.main()
