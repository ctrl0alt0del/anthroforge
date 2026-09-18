"""Shared transfer mathematics and closed authoring contracts, without Blender."""
import copy
import itertools
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from core.authoring.errors import AuthoringError
from core.authoring.schema import validate
from core.authoring.transfer_field import fit, evaluate, jacobians, serialize, deserialize
from core.authoring.transfer_quality import field_report
from core.authoring.transfer_meshes import build

CORNERS = np.array(list(itertools.product((-1., 1.), repeat=3)))
MATRIX = np.array([[1.4, .2, -.1], [0., .8, .3], [.1, 0., 1.2]])
SHIFT = np.array([8., -3., 2.])


def nonlinear_target():
    target = CORNERS.copy()
    target[:, 0] += .3*CORNERS[:, 1]*CORNERS[:, 2]
    return target


def mesh_row(matrix):
    geometry = dict(vertices=CORNERS.tolist(), triangles=[[0, 1, 2], [1, 2, 3]], matrix=matrix.tolist())
    return dict(geometry=geometry, topology_digest='same-topology', geometry_digest='geometry', color=[.8, .3, .2, 1])


def request():
    binding = dict(tri_vidx=[0, 1, 2], tri_weights=[1., 0., 0.])
    source = dict(object='AtlasBone', topology_digest='vertices-v2:source', surface_binding=binding)
    target = dict(document_id='discovery', expected_draft_revision=1, region='/skeleton_profiles/body/regions/test',
                  topology_digest='vertices-v2:target', surface_binding=binding)
    pairs = [dict(id=str(i), source=source, target=target) for i in range(4)]
    params = dict(scene_id='root', expected_scene_revision='revision', source_objects=['AtlasMuscle'],
                  correspondences=pairs, settings=dict(max_landmark_error=.001))
    return dict(version='0.4.0', message_type='request', request_id='transfer', op='anatomy.transfer_preview', params=params)


class TransferFieldTests(unittest.TestCase):
    def test_affine_field_preserves_off_landmark_points_and_jacobian(self):
        field = fit(CORNERS, CORNERS @ MATRIX.T+SHIFT)
        probes = np.array([[.15, -.7, 1.2], [0., 0., 0.], [-2., 3., -4.]])
        np.testing.assert_allclose(evaluate(field, probes), probes @ MATRIX.T+SHIFT, atol=1e-12)
        np.testing.assert_allclose(jacobians(field, probes), np.repeat(MATRIX[None], len(probes), axis=0), atol=1e-12)
        self.assertEqual(field_report(field, probes)['foldover_samples'], 0)

    def test_translation_scale_and_serialization_do_not_change_map(self):
        source = CORNERS*1e-3+1e6
        target = CORNERS @ MATRIX.T+SHIFT
        field = deserialize(serialize(fit(source, target)))
        np.testing.assert_allclose(evaluate(field, source), target, atol=1e-8)
        np.testing.assert_allclose(evaluate(field, source, 1), evaluate(field, source, 100), atol=1e-12)

    def test_nonlinear_constraints_interpolate_and_derivative_is_correct(self):
        field = fit(CORNERS, nonlinear_target())
        np.testing.assert_allclose(evaluate(field, CORNERS), nonlinear_target(), atol=1e-12)
        point, step = np.array([[.2, .1, -.4]]), 1e-5
        numeric = np.column_stack([(evaluate(field, point+axis*step)-evaluate(field, point-axis*step))[0]/(2*step)
                                   for axis in np.eye(3)])
        np.testing.assert_allclose(jacobians(field, point)[0], numeric, rtol=1e-8, atol=1e-10)

    def test_smoothing_trades_off_landmark_error_explicitly(self):
        exact = fit(CORNERS, nonlinear_target())
        smooth = fit(CORNERS, nonlinear_target(), smoothing=.1)
        self.assertLess(np.max(np.abs(evaluate(exact, CORNERS)-nonlinear_target())), 1e-12)
        self.assertGreater(np.max(np.abs(evaluate(smooth, CORNERS)-nonlinear_target())), .001)

    def test_rank_duplicate_and_invalid_inputs_fail_explicitly(self):
        for source in (CORNERS[:3], CORNERS[:4], np.vstack((CORNERS, CORNERS[0]))):
            with self.subTest(source=source), self.assertRaises(AuthoringError):
                fit(source, source)
        for invalid in (np.full((8, 3), np.nan), np.zeros((8, 3)), np.ones((8, 2))):
            with self.subTest(invalid=invalid), self.assertRaises(AuthoringError):
                fit(invalid, CORNERS)

    def test_global_reflection_requires_explicit_opt_in(self):
        field = fit(CORNERS, CORNERS*np.array([-1, 1, 1]))
        self.assertEqual(field_report(field, CORNERS)['foldover_samples'], 8)
        allowed = field_report(field, CORNERS, allow_reflection=True)
        self.assertEqual(allowed['foldover_samples'], 0)
        self.assertEqual(allowed['orientation'], -1)

    def test_collapsed_target_is_flagged(self):
        target = CORNERS.copy(); target[:, 2] = 0
        field = fit(CORNERS, target)
        self.assertEqual(field_report(field, CORNERS)['foldover_samples'], 8)

    def test_reflection_opt_in_does_not_accept_mixed_local_orientations(self):
        target = CORNERS.copy(); target[:, 0] *= target[:, 1]
        field = fit(CORNERS, target)
        self.assertGreater(field_report(field, CORNERS, allow_reflection=True)['foldover_samples'], 0)


class TransferMeshTests(unittest.TestCase):
    def test_baking_a_reflected_source_object_preserves_winding(self):
        matrix = np.diag([-1., 1., 1., 1.])
        sources = dict(muscle=mesh_row(matrix))
        pairs = [dict(id=str(i), source=s.tolist(), target=s.tolist()) for i, s in enumerate(CORNERS)]
        result = build(sources, ['muscle'], pairs, dict(max_landmark_error=1e-6), [])
        self.assertEqual(result['meshes'][0]['triangles'], [[2, 1, 0], [3, 2, 1]])

    def test_meshes_and_annotations_share_world_map_without_source_mutation(self):
        matrix = np.eye(4); matrix[:3, 3] = [.1, .2, .3]
        sources = dict(first=mesh_row(np.eye(4)), second=mesh_row(matrix))
        before = copy.deepcopy(sources)
        pairs = [dict(id=str(i), source=s.tolist(), target=(s @ MATRIX.T+SHIFT).tolist()) for i, s in enumerate(CORNERS)]
        result = build(sources, list(sources), pairs, dict(max_landmark_error=1e-6), [dict(id='a', point=[0, 0, 0])])
        for row, shift in zip(result['meshes'], (np.zeros(3), matrix[:3, 3])):
            np.testing.assert_allclose(row['vertices'], (CORNERS+shift) @ MATRIX.T+SHIFT, atol=1e-12)
            self.assertEqual(row['triangles'], sources[row['source_object']]['geometry']['triangles'])
        np.testing.assert_allclose(result['annotations'][0]['transferred_point'], SHIFT, atol=1e-12)
        self.assertEqual(sources, before)
        self.assertEqual(result['validation']['anatomy'], 'not_evaluated')

    def test_unresolved_reflection_is_reported_and_allowed_winding_reverses(self):
        sources = dict(muscle=mesh_row(np.eye(4)))
        pairs = [dict(id=str(i), source=s.tolist(), target=(s*[-1, 1, 1]).tolist()) for i, s in enumerate(CORNERS)]
        settings = dict(max_landmark_error=1e-6)
        rejected = build(sources, ['muscle'], pairs, settings, [])
        self.assertEqual(rejected['status'], 'unresolved')
        accepted = build(sources, ['muscle'], pairs, dict(settings, allow_reflection=True), [])
        self.assertEqual(accepted['status'], 'success')
        self.assertEqual(accepted['meshes'][0]['triangles'], [[2, 1, 0], [3, 2, 1]])


class TransferSchemaTests(unittest.TestCase):
    def test_contract_accepts_indexed_landmarks_and_explicit_tolerance(self):
        validate(request(), 'protocol')

    def test_contract_rejects_missing_tolerance_extra_knobs_and_coordinate_bindings(self):
        first = request(); del first['params']['settings']['max_landmark_error']
        second = request(); second['params']['settings']['per_muscle_scale'] = 1
        third = request(); third['params']['correspondences'][0]['source']['surface_binding'] = dict(point=[0, 0, 0])
        for payload in (first, second, third):
            with self.subTest(payload=payload), self.assertRaises(AuthoringError):
                validate(payload, 'protocol')


if __name__ == '__main__':
    unittest.main()
