"""Shape response, bounded fitting and declaration-dependent metrics."""
import unittest
from copy import deepcopy
import numpy as np
from core.authoring import fitting, metrics, lowering
from core.authoring.errors import AuthoringError


def output():
    u, s = np.linspace(0, 1, 9), np.linspace(0, 1, 17)
    grid = np.array([[[2*x-1, 0, 4*z] for z in s] for x in u])
    config = dict(enabled=True, mode='control_point', amount=.2, flip_normals=False, control=[.5, .5], radius=4., direction_depth=1., falloff='gaussian', boundary=dict(along=.05, across=.1, strength=1., power=1.2))
    return dict(base=grid.reshape((-1, 3)).tolist(), inflated=grid.reshape((-1, 3)).tolist(), u=u.tolist(), s=s.tolist(), fibers=[dict(closed=False)]*3, config=config)


class ShapeTests(unittest.TestCase):
    def test_fractional_node_count_is_rejected(self):
        with self.assertRaises(AuthoringError) as error:
            lowering.apply_parameters({}, dict(nodes_per_fiber=12.5))
        self.assertEqual(error.exception.code, 'INTEGER_PARAMETER_REQUIRED')

    def test_concave_cap_is_not_measured_as_fan(self):
        polygon = np.array([[0,0,0], [2,0,0], [1,.5,0], [2,1,0], [0,1,0]])
        with self.assertRaises(AuthoringError) as error:
            metrics.cap(polygon, 2)
        self.assertEqual(error.exception.code, 'CONCAVE_CLOSURE_UNSUPPORTED')

    def test_bounded_search_changes_height_without_fibers(self):
        value = output()
        shape = dict(targets=[dict(metric='height', range=[.5, .6], closure='none', hard=True)], fitting=dict(enabled=True, parameters=['max_inflation'], max_evaluations=20, step=.1))
        result = fitting.fit(value, shape)
        self.assertEqual(result['fitting']['state'], 'resolved')
        self.assertLessEqual(result['fitting']['evaluations'], 20)
        self.assertEqual(result['fibers'], value['fibers'])
        self.assertEqual(result['base'], value['base'])

    def test_exhaustion_reports_residual(self):
        value = output()
        shape = dict(targets=[dict(metric='height', range=[10, 11], closure='none', hard=True)], fitting=dict(enabled=True, parameters=['max_inflation'], max_evaluations=2, step=.1))
        result = fitting.fit(value, shape)
        self.assertEqual(result['fitting']['state'], 'unresolved')
        self.assertGreater(result['fitting']['residuals'][0]['residual'], 0)

    def test_boundary_and_belly_change_profile(self):
        value = output()
        first, _ = fitting.evaluate(value, value['config'], [])
        config = deepcopy(value['config'])
        config['control'][1] = .25
        config['boundary']['along'] = .2
        second, _ = fitting.evaluate(value, config, [])
        self.assertLess(fitting.metrics(second)['belly_position'], fitting.metrics(first)['belly_position'])
        self.assertNotEqual(first['inflated'], second['inflated'])

    def test_volume_unavailable_without_closure(self):
        result = fitting.errors(dict(height=1), [dict(metric='volume', range=[0, 1], closure='none', hard=True)])
        self.assertEqual(result[0]['state'], 'unsupported')

    def test_open_cube_planar_cap(self):
        points = [[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]]
        faces = [[3,2,1,0],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
        result = metrics.closure(dict(inflated=points, faces=faces), 'planar_caps')
        self.assertAlmostEqual(result['volume'], 1)
        self.assertAlmostEqual(result['area'], 6)

    def test_intent_preserves_sampling(self):
        volume = dict(mode='control_point', amount=dict(fraction=.1), radius=dict(value=1), control=[.5,.5], boundary=dict(along=.1))
        lowering.shape_intent(volume, dict(height_scale=2, width_scale=1.5, belly_position=.4, taper=.2))
        self.assertEqual(volume['amount']['fraction'], .2)
        self.assertEqual(volume['radius']['value'], 1.5)
        self.assertEqual(volume['control'][1], .4)


if __name__ == '__main__':
    unittest.main()
