from dataclasses import replace
import unittest
import numpy as np
from test_muscle_stacking import inflated
from stack_fixture_adapter import payload, solve
from pair_fixture_adapter import wait
from pair_fixtures import rectangle
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.model import StackingSettings, material
from core.muscle_stacking.native import NativeStackEngine


def islands(name, locations):
    parts = [inflated(name, z, z+.2, (x, x+1, 0, 1)) for x, z in locations]
    base, own, directions = (np.concatenate([getattr(p, key) for p in parts]) for key in ('base', 'own', 'direction'))
    faces = np.concatenate([p.faces+i*len(p.base) for i, p in enumerate(parts)])
    indices = np.arange(len(base))[:, None]
    m = material(base, faces, indices, np.ones(indices.shape), ())
    return replace(parts[0], base=base, own=own, direction=directions, faces=faces, material=m,
        parts=np.zeros(len(faces), dtype=np.int64), sources=np.arange(len(faces), dtype=np.int64))


class StackingLifecycle(unittest.TestCase):
    def setUp(self):
        self.engine = NativeStackEngine(); self.addCleanup(self.engine.close); self.generation = 0
        self.values = [inflated('under', 0, .3), inflated('cover', .1, .2)]
        self.settings = DetectionSettings(stacking=StackingSettings())

    def run_job(self, values=None, settings=None):
        self.generation += 1
        self.engine.submit(self.values if values is None else values, settings or self.settings, self.generation)
        return wait(self.engine), {k.muscle: v for k, v in self.engine.surfaces().items()}

    def test_unchanged_outer_edit_and_removal(self):
        _, first = self.run_job(); report, second = self.run_job()
        np.testing.assert_array_equal(first['cover'], second['cover'])
        self.assertEqual(report['timings']['stack_solve_ms'], 0)
        self.values[0] = replace(self.values[0], own=self.values[0].own+[0, 0, .1])
        _, edited = self.run_job(); np.testing.assert_allclose(edited['cover'][:, 2], .6, atol=2e-6)
        _, deleted = self.run_job(self.values[1:]); np.testing.assert_array_equal(deleted['cover'], self.values[1].own)

    def test_local_order_cache_tracks_base_direction_group(self):
        self.run_job(); a, b = self.values
        report, _ = self.run_job([replace(a, base=a.base+[0, 0, .1]), b])
        self.assertEqual(report['pairs'][0]['order']['status'], 'coincident_bases')
        report, _ = self.run_job([replace(a, direction=-a.direction), b])
        self.assertNotEqual(report['pairs'][0]['order']['status'], 'supported')
        report, out = self.run_job([replace(a, group=b.group), b])
        self.assertFalse(report['pairs']); np.testing.assert_array_equal(out['cover'], b.own)

    def test_cache_eviction_and_bound_change(self):
        first, out = self.run_job(); config = replace(self.settings, cache_bytes=0)
        for _ in range(2):
            report, repeated = self.run_job(settings=config)
            np.testing.assert_allclose(repeated['cover'], out['cover'], atol=2e-6)
        report, unchanged = self.run_job(settings=replace(config, displacement=.01))
        self.assertEqual(report['stacking']['status'], 'complete')
        np.testing.assert_allclose(unchanged['cover'], out['cover'], atol=2e-6)

    def test_invalid_domain_blocks_dependents_but_not_unrelated(self):
        a, b = self.values; independent = [inflated('c', 0, .3, (5, 7, 0, 2)), inflated('d', .1, .2, (5, 7, 0, 2))]
        report, out = self.run_job([replace(a, valid=False), b, *independent])
        self.assertEqual(report['stacking']['status'], 'incomplete')
        np.testing.assert_array_equal(out['cover'], b.own)
        np.testing.assert_allclose(out['d'][:, 2], .5, atol=2e-6)

    def test_cycle_blocks_only_component(self):
        cycle = [islands('a', [(-4, 0), (4, .1)]), islands('b', [(-4, .1), (0, 0)]), islands('c', [(0, .1), (4, 0)])]
        independent = [inflated('d', 0, .3, (10, 12, 0, 2)), inflated('e', .1, .2, (10, 12, 0, 2))]
        report, out = self.run_job(cycle+independent)
        states = {r['domain']['muscle']: r['status'] for r in report['stacking']['domains']}
        self.assertEqual([states[k] for k in ('a', 'b', 'c')], ['blocked']*3)
        for side in cycle: np.testing.assert_array_equal(out[side.key.muscle], side.own)
        np.testing.assert_allclose(out['e'][:, 2], .5, atol=2e-6)

    def test_cancel_stale_export_and_recovery(self):
        self.engine.submit(self.values, self.settings, 900); self.engine.cancel()
        with self.assertRaises(ValueError): wait(self.engine)
        self.run_job()
        with self.assertRaises(ValueError): self.engine.order_footprint(0, 900)
        report, _ = self.run_job([]); self.assertFalse(report['stacking']['domains'])
        self.assertEqual(self.run_job()[0]['stacking']['status'], 'complete')

    def test_excluded_relation_and_mirror_identity(self):
        a, b = self.values
        keys = tuple((d.key.muscle, d.key.instance, d.key.side) for d in self.values)
        settings = replace(self.settings, stacking=StackingSettings(exclusions=(keys,)))
        report, out = self.run_job(settings=settings)
        self.assertEqual(report['pairs'][0]['order']['status'], 'excluded'); np.testing.assert_array_equal(out['cover'], b.own)
        values = [replace(d, key=replace(d.key, instance='mirror', side='B')) for d in self.values]
        report, _ = self.run_job(values)
        self.assertTrue(all(d['domain']['instance'] == 'mirror' and d['domain']['side'] == 'B' for d in report['stacking']['domains']))

    def test_strided_inputs_are_copied_before_native_access(self):
        a, b = self.values
        values = [replace(v, faces=v.faces[:, ::-1], material=replace(v.material, faces=v.material.faces[:, ::-1])) for v in (a, b)]
        report, out = self.run_job(values)
        self.assertEqual(report['stacking']['status'], 'complete')
        np.testing.assert_allclose(out['cover'][:, 2], .5, atol=2e-6)

    def test_invalid_interpolation_shape_rejected_before_pointer_use(self):
        a, b = self.values; b = replace(b, material=replace(b.material, weights=b.material.weights[:-1]))
        with self.assertRaisesRegex(ValueError, 'STACK_MATERIAL_SIZE'): self.run_job([a, b])

    def test_submitted_material_and_geometry_are_owned(self):
        values = [replace(v, own=v.own.copy(), material=replace(v.material, vertices=v.material.vertices.copy())) for v in self.values]
        self.engine.submit(values, self.settings, 400)
        values[0].own[:]=500; values[1].material.vertices[:]=700
        result=wait(self.engine); self.assertEqual(result['stacking']['status'], 'complete')
        surface=next(v for k,v in self.engine.surfaces().items() if k.muscle=='cover')
        np.testing.assert_allclose(surface[:,2], .5, atol=2e-6)
