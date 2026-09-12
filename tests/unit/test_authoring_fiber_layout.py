"""Geometric behavior, finite minimum proof checks and closed planner protocol."""
import itertools
import unittest
import numpy as np
from core.authoring import fiber_layout, layout_patch, layout_routing, layout_reduction as reduction
from core.authoring.errors import AuthoringError
from core.authoring.model import Budget
from core.authoring.validation import request as validate_request
from tools.authoring_schema_v04 import authoring, protocol
from core.authoring.schema import bundled


def patch(function, width=8, length=12):
    grid = [[function(u, v) for v in np.linspace(0, 1, length+1)] for u in np.linspace(0, 1, width+1)]
    polygons = []
    for i in range(width):
        for j in range(length):
            a, b, c, d = grid[i][j], grid[i+1][j], grid[i+1][j+1], grid[i][j+1]
            polygons.extend(([a, b, c], [a, c, d]))
    return polygons, [grid[0][0], grid[-1][0], grid[-1][-1], grid[0][-1]]


def flat(u, v):
    return [4*u, 8*v, 0.]


def transverse(u, v):
    angle = (u-.5)*1.8
    return [3*np.sin(angle), 8*v, 3*np.cos(angle)]


def longitudinal(u, v):
    angle = (v-.5)*1.8
    return [4*u, 5*np.sin(angle), 5*np.cos(angle)]


def planner_request(**options):
    binding = dict(tri_vidx=[0, 1, 2], tri_weights=[1, 0, 0])
    landmarks = {key: binding for key in ('start_left', 'start_right', 'end_right', 'end_left')}
    params = dict(scene_id='scene', document_id='doc', expected_draft_revision=1, expected_scene_revision='one', region='/skeleton_profiles/default/regions/area', boundary_landmarks=landmarks, tolerance=.05)
    params.update(options)
    return dict(version='0.4.0', message_type='request', request_id='layout', op='anatomy.plan_fibers', params=params)


class SurfaceLayoutTests(unittest.TestCase):
    def test_flat_large_area_only_needs_two_boundary_fibers(self):
        for scale in (1, 10):
            polygons, corners = patch(lambda u, v: np.asarray(flat(u, v))*scale)
            result = fiber_layout.plan(polygons, corners, .0001, 9, 33)
            self.assertEqual((result['fiber_count'], result['middle_point_count']), (2, 0))
            self.assertLess(result['max_sampled_error'], .0001)

    def test_transverse_curvature_adds_fibers_not_touches(self):
        result = fiber_layout.plan(*patch(transverse), .06, 17, 33)
        self.assertGreater(result['fiber_count'], 2)
        self.assertEqual(result['middle_point_count'], 0)
        self.assertLessEqual(result['max_sampled_error'], .06)
        self.assertFalse(result['native_solver_validated'])

    def test_longitudinal_curvature_does_not_become_hard_touches(self):
        result = fiber_layout.plan(*patch(longitudinal), .06, 9, 65)
        self.assertEqual(result['fiber_count'], 2)
        self.assertEqual(result['middle_point_count'], 0)
        self.assertEqual(len(result['fibers'][0]['reference_path']), 65)
        self.assertFalse(result['native_solver_validated'])
        self.assertLessEqual(result['max_sampled_error'], .06)

    def test_lower_tolerance_does_not_reduce_crosswise_count(self):
        first = fiber_layout.plan(*patch(transverse), .15, 17, 33)
        second = fiber_layout.plan(*patch(transverse), .035, 17, 33)
        self.assertGreaterEqual(second['fiber_count'], first['fiber_count'])

    def test_budgets_do_not_return_an_inadequate_success(self):
        with self.assertRaisesRegex(AuthoringError, 'max_fibers'):
            fiber_layout.plan(*patch(transverse), .06, 17, 33, max_fibers=2)
        result = fiber_layout.plan(*patch(longitudinal), .06, 9, 33, max_points_per_fiber=2)
        self.assertEqual(result['point_count'], 4)

    def test_crossed_or_interior_landmarks_rejected(self):
        polygons, corners = patch(flat)
        with self.assertRaises(AuthoringError) as error:
            fiber_layout.plan(polygons, [corners[i] for i in (0, 2, 1, 3)], .1)
        self.assertEqual(error.exception.code, 'LAYOUT_LANDMARK_ORDER')
        with self.assertRaises(AuthoringError) as error:
            fiber_layout.plan(polygons, [[2, 4, 0]]+corners[1:], .1)
        self.assertEqual(error.exception.code, 'LAYOUT_LANDMARK_NOT_BOUNDARY_VERTEX')

    def test_disconnected_area_and_hole_rejected(self):
        polygons, _ = patch(flat, 3, 3)
        for selected in (polygons[:2]+polygons[-2:], polygons[:8]+polygons[10:]):
            with self.assertRaises(AuthoringError):
                layout_patch.mesh(selected)

    def test_boundary_ear_remains_a_valid_chart(self):
        polygons = [[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[1, 0, 0], [1, 1, 0], [0, 1, 0]], [[1, 0, 0], [2, 0, 0], [1, 1, 0]], [[2, 0, 0], [2, 1, 0], [1, 1, 0]]]
        result = fiber_layout.plan(polygons, [[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], .001, 5, 9)
        self.assertEqual(result['fiber_count'], 2)

    def test_cancellation_and_large_mesh_budget_are_explicit(self):
        with self.assertRaises(AuthoringError) as error:
            fiber_layout.plan(*patch(flat), .01, budget=Budget(cancelled=True))
        self.assertEqual(error.exception.code, 'CANCELLED')
        with self.assertRaises(AuthoringError) as error:
            layout_patch.mesh([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]]*8193)
        self.assertEqual(error.exception.code, 'LAYOUT_PATCH_BUDGET')

    def test_narrow_unsampled_ridge_is_not_silently_accepted(self):
        shape = lambda u, v: [4*u, 8*v, .8*max(0, 1-abs(u-.2)/.04)]
        with self.assertRaises(AuthoringError) as error:
            fiber_layout.plan(*patch(shape, 20, 8), .01, 5, 33)
        self.assertEqual(error.exception.code, 'LAYOUT_TOLERANCE_UNREACHABLE')


class ShortcutMinimumTests(unittest.TestCase):
    def test_graph_count_and_touch_tie_break_match_exhaustive_subsets(self):
        random = np.random.default_rng(10)
        for _ in range(20):
            allowed = random.random((7, 7)) > .6
            allowed[np.arange(6), np.arange(1, 7)] = True
            costs = random.integers(2, 9, 7).tolist()
            selected = reduction.shortest_path(7, lambda i, j: allowed[i, j], costs)
            paths = [[0]+[i+1 for i, keep in enumerate(mask) if keep]+[6] for mask in itertools.product((False, True), repeat=5)]
            valid = [p for p in paths if all(allowed[i, j] for i, j in zip(p, p[1:]))]
            expected = min((len(p), sum(costs[i] for i in p)) for p in valid)
            self.assertEqual((len(selected), sum(costs[i] for i in selected)), expected)

    def test_band_selector_matches_exhaustive_geometric_layouts(self):
        across, stations = np.linspace(0, 1, 7), np.linspace(0, 1, 17)
        rows = [np.array([transverse(u, t) for t in stations]) for u in across]
        routes = [dict(points=row[[0, -1]], row=row) for row in rows]
        cloud = np.array([(u, t) for u in across for t in stations]), np.concatenate(rows)
        chosen, _ = reduction.select_fibers(routes, across, cloud, .1, 7, 2)
        paths = [[0]+[i+1 for i, keep in enumerate(mask) if keep]+[6] for mask in itertools.product((False, True), repeat=5)]
        valid = [p for p in paths if all(reduction.band_error(rows, across, cloud, i, j) <= .1 for i, j in zip(p, p[1:]))]
        self.assertEqual(len(chosen), min(map(len, valid)))


class LayoutProtocolTests(unittest.TestCase):
    def test_pinned_schema_matches_generator(self):
        self.assertEqual(bundled('protocol', '0.4.0'), protocol(authoring()['$defs']))
        self.assertEqual(validate_request(planner_request())['op'], 'anatomy.plan_fibers')

    def test_invalid_tolerance_budgets_and_unknown_fields_rejected(self):
        for options in (dict(tolerance=0), dict(tolerance=float('nan')), dict(candidate_count=66), dict(max_fibers=1), dict(max_points_per_fiber=129), dict(max_solver_calls=0), dict(solver_budget_ms=10001), dict(create=True)):
            with self.assertRaises(AuthoringError):
                validate_request(planner_request(**options))


class SparseRoutingTests(unittest.TestCase):
    def test_solver_handles_curvature_with_no_middle_points(self):
        reference = np.asarray([longitudinal(0, t) for t in np.linspace(0, 1, 65)])
        calls = []
        solve = lambda indices: calls.append(indices) or dict(path=reference.tolist(), validated=True)
        result = layout_routing.refine(reference, solve, .01, 4, Budget())
        self.assertEqual(calls, [[0, 64]])
        self.assertEqual(result['indices'], [0, 64])

    def test_only_measured_route_deviation_adds_a_control(self):
        reference = np.asarray([[0, 0, 0], [1, 1, 0], [2, 0, 0]], float)
        calls = []
        solve = lambda indices: calls.append(indices) or dict(path=reference[indices].tolist(), validated=True)
        result = layout_routing.refine(reference, solve, .01, 4, Budget())
        self.assertEqual(calls, [[0, 2], [0, 1, 2]])
        self.assertEqual(result['corrections'][0]['reason'], 'solved_route_deviation')
        self.assertGreater(result['corrections'][0]['before_error'], .5)
        self.assertLess(result['corrections'][0]['after_error'], .01)

    def test_correction_stops_if_it_does_not_improve_the_route(self):
        reference = np.asarray([[0, 0, 0], [1, 1, 0], [2, 0, 0]], float)
        calls = []
        solve = lambda indices: calls.append(indices) or dict(path=reference[[0, -1]].tolist(), validated=True)
        with self.assertRaises(AuthoringError) as error:
            layout_routing.refine(reference, solve, .01, 4, Budget())
        self.assertEqual(error.exception.code, 'LAYOUT_ROUTE_CORRECTION_STALLED')
        self.assertEqual(len(calls), 2)

    def test_two_middle_point_cap_cannot_be_bypassed(self):
        reference = np.array([[0, 0, 0], [1, 3, 0], [2, -2, 0], [3, 1, 0], [4, 0, 0]], float)
        calls = []
        solve = lambda indices: calls.append(indices) or dict(path=reference[indices].tolist(), validated=True)
        with self.assertRaises(AuthoringError) as error:
            layout_routing.refine(reference, solve, .01, 4, Budget())
        self.assertEqual(error.exception.code, 'LAYOUT_POINT_BUDGET')
        self.assertLessEqual(max(map(len, calls)), 4)

    def test_invalid_native_route_is_not_accepted_or_flooded_with_touches(self):
        reference = np.array([[0, 0, 0], [1, 1, 0], [2, 0, 0]], float)
        solve = lambda indices: dict(path=reference.tolist(), validated=False)
        with self.assertRaises(AuthoringError) as error:
            layout_routing.refine(reference, solve, .01, 4, Budget())
        self.assertEqual(error.exception.code, 'LAYOUT_ROUTE_UNSAFE')


if __name__ == '__main__':
    unittest.main()
