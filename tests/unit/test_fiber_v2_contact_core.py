import unittest
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from core.vcp.v2.collision import build_native_collision_world
from core.vcp.v2.collision_native import (native_contact_block_solve,
                                          native_structural_contact_responses)
from core.vcp.v2.contact_core import (V2Contact, _collapse_contacts,
                                      _adapt_quality, _effective_settings, _limiter_changed, _merge_contacts,
                                      _stationary_rejection, _update_regularization,
                                      begin_contact_core, solve_contact_core)
from core.vcp.v2.contracts import V2ColliderSnapshot, V2Settings
from core.vcp.v2.structural import _base_bands, _static_settings, assemble_normal_matrix
from core.vcp.v2.trust_sqp import update_trust_radius
from core.vcp.v3.policy import V3_PRODUCTION_POLICY
from tests.unit.test_fiber_v2_solver import _box_request


def _contact_state(request, contact):
    return SimpleNamespace(request=request, contacts={contact.key: contact}, injected=0,
                           retired=0, mu=100.0, energy_streak=3)


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
    def test_persistent_native_session_fuses_contacts_and_validation(self):
        request = _box_request(); world = build_native_collision_world(request.colliders)
        points = np.linspace((-1, .1, 0), (1, .1, 0), request.settings.node_count)
        edges = tuple((index, index + 1) for index in range(len(points) - 1))
        owners = tuple(("", "") for _edge in edges); session = world.begin_v3_session(owners)
        contacts, validation = session.measure(points, 0.0, .2, .1)
        expected = world.contact_pairs(points, edges, owners, 0.0, .2)
        self.assertEqual(contacts.pairs, expected.pairs); self.assertEqual(validation.clear,
                                                                         world.validate(points, edges, owners, 0.0, .1).clear)
        self.assertEqual(session.stats()["measures"], 1)

    def test_persistent_native_session_reuses_structural_workspace(self):
        request = _box_request(); world = build_native_collision_world(request.colliders)
        count = request.settings.node_count; owners = tuple(("", "") for _edge in range(count - 1))
        session = world.begin_v3_session(owners); reference = np.linspace((-1, .2, 0), (1, .2, 0), count)
        bands = _base_bands(count, _static_settings(request.settings)); rhs = request.settings.fidelity_weight * reference
        rows = ((8, .2, (0, 1, 0)),); pins, targets = (0, count - 1), (reference[0], reference[-1])
        expected = native_structural_contact_responses(bands, rhs, rows, pins, targets)
        first = session.structural_responses(bands, rhs, rows, pins, targets)
        second = session.structural_responses(bands, rhs, rows, pins, targets)
        np.testing.assert_array_equal(first[0], expected[0]); np.testing.assert_array_equal(second[1], expected[1])
        self.assertEqual(session.stats()["structural_solves"], 2)

    def test_persistent_native_ccd_matches_reference_driver(self):
        request = _box_request()
        reference = solve_contact_core(request, use_planner=False, use_filter_sqp=True,
                                       policy=V3_PRODUCTION_POLICY, native_session=False)
        fused = solve_contact_core(request, use_planner=False, use_filter_sqp=True,
                                   policy=V3_PRODUCTION_POLICY, native_session=True)
        np.testing.assert_array_equal(fused.result.points, reference.result.points)
        self.assertEqual(fused.result.termination, reference.result.termination)
        stats = dict(fused.trace.native_session_stats)
        self.assertGreater(stats["sweeps"], 0); self.assertGreater(stats["sweep_capacity"], 0)

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

    def test_sqp_collapses_adjacent_triangle_duplicate_contacts(self):
        first = V2Contact(8, .63, "C", 2, "DISTANCE", (0, 1, 0), 0.0, multiplier=4.0)
        duplicate = V2Contact(8, .63, "C", 10, "DISTANCE", (0, 1, 0), 0.0, multiplier=7.0)
        distinct = V2Contact(8, .63, "C", 11, "DISTANCE", (1, 0, 0), 0.0)
        output = _collapse_contacts(_contact_state(_box_request(), first), (duplicate, distinct, first))
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0].multiplier, 7.0)

    def test_limiter_tracks_same_feature_linearization_drift(self):
        first = V2Contact(3, .2, "C", 7, "LIMITING", (0, 1, 0), 0.0, 0.0)
        moved = replace(first, factor=.8, gap=-.1, linearized_gap=-.1)
        self.assertTrue(_limiter_changed(SimpleNamespace(), first, moved))

    def test_adaptive_quality_detects_collapsed_sampling(self):
        points = np.asarray(((0, 0, 0), (.01, 0, 0), (.02, 0, 0), (1, 0, 0)), dtype=float)
        state = SimpleNamespace(policy=V3_PRODUCTION_POLICY, points=points,
            accepted=4, rejected=0, condition=1.0, quality_adapted=False, quality_spacing=False,
            quality_trigger="", energy_streak=3, pending_sqp=None)
        _adapt_quality(state)
        self.assertTrue(state.quality_adapted); self.assertTrue(state.quality_spacing)

    def test_adaptive_quality_never_restores_curvature(self):
        settings = V2Settings(node_count=4, curvature_weight=7.0)
        state = SimpleNamespace(policy=V3_PRODUCTION_POLICY,
                                request=SimpleNamespace(settings=settings), quality_adapted=True)
        self.assertEqual(_effective_settings(state).curvature_weight, 0.0)

    def test_adaptive_quality_ignores_condition_without_collapse(self):
        points = np.asarray(((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)), dtype=float)
        state = SimpleNamespace(policy=V3_PRODUCTION_POLICY, points=points,
            accepted=4, rejected=100, condition=1.0e30, quality_adapted=False,
            quality_spacing=False, quality_trigger="")
        _adapt_quality(state); self.assertFalse(state.quality_adapted)

    def test_adaptive_regularization_grows_and_shrinks_step_penalty(self):
        state = SimpleNamespace(policy=V3_PRODUCTION_POLICY,
            regularization_scale=10.0, sqp_regularization=.01, regularization_increases=0,
            regularization_decreases=0, regularization_history=[], condition=1.0)
        _update_regularization(state, -.5, False)
        self.assertEqual(state.sqp_regularization, .04)
        _update_regularization(state, .9, True)
        self.assertEqual(state.sqp_regularization, .02)

    def test_sqp_repeated_stationary_model_rejection_converges(self):
        contact = V2Contact(0, .5, "C", 2, "DISTANCE", (1, 0, 0), 0.0)
        state = _contact_state(_box_request(), contact)
        state.metrics = SimpleNamespace(feasible=True); state.stalled = 2
        state.fixed_residual = 1.0e-6; state.stationarity = 1.0e-6
        self.assertTrue(_stationary_rejection(state, "MODEL_RATIO:-inf"))
        state.contacts = {contact.key: replace(contact, feature_id="LIMITING")}
        self.assertFalse(_stationary_rejection(state, "MODEL_RATIO:-inf"))

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

    def test_filter_sqp_intersecting_seed_converges_with_fewer_rejections(self):
        request = _box_request(); baseline = solve_contact_core(request, use_planner=False)
        package = solve_contact_core(request, use_planner=False, use_filter_sqp=True)
        self.assertTrue(package.result.validated, package.result.message)
        self.assertEqual(package.result.termination.value, "CONVERGED")
        self.assertLess(package.result.diagnostics.rejected_steps,
                        baseline.result.diagnostics.rejected_steps)

    def test_diagnostic_trace_is_opt_in_and_geometry_neutral(self):
        request = _box_request()
        plain = solve_contact_core(request, use_planner=False, use_filter_sqp=True)
        traced = solve_contact_core(request, use_planner=False, use_filter_sqp=True,
                                    diagnostic_trace=True)
        self.assertEqual(plain.result.points, traced.result.points)
        self.assertEqual(plain.trace.iteration_trace, ())
        self.assertGreater(len(traced.trace.iteration_trace), 3)
        self.assertEqual(len(traced.trace.reference_points), request.settings.node_count)

    def test_diagnostic_trace_records_solver_and_collision_evidence(self):
        request = _box_request(); package = solve_contact_core(request, use_planner=False,
            use_filter_sqp=True, diagnostic_trace=True)
        rows = package.trace.iteration_trace; stages = {row["stage"] for row in rows}
        self.assertTrue({"SEED", "PROPOSE", "FINISH"}.issubset(stages))
        proposal = next(row for row in rows if row["stage"] == "PROPOSE")
        self.assertEqual(len(proposal["turn_degrees"]), request.settings.node_count)
        self.assertEqual(len(proposal["gradient"]["total_norms"]), request.settings.node_count)
        self.assertIn("sqp", proposal); self.assertIn("feasibility", proposal)

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
