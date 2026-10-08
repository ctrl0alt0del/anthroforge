"""Regression: exact calf capture from the failed 2026-10-07 playground.

Fixture retains source bases, directions, provenance, material interpolation and
pins. Soleus depths are (2, 1.28, 1.08, .52); no geometry was simplified.
Blender qualification separately checks mirrors, bones, editing and reopening.
"""
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
from core.muscle_pairs.model import DomainKey, snapshot
from core.muscle_stacking.model import material
from core.muscle_stacking.native import NativeStackEngine
from test_explicit_stacking import config
from pair_fixture_adapter import wait


def calf_domain(data, ident, name):
    values = [data[f'{ident}_{key}'] for key in ('base', 'own', 'direction', 'faces', 'parts', 'sources')]
    domain = snapshot(DomainKey('calf', name), name, '', *values, displacement=2.)
    keys = ('vertices', 'material_faces', 'interpolation', 'weights', 'fixed')
    return replace(domain, material=material(*(data[f'{ident}_{key}'] for key in keys)))


class VectorCalfRegression(unittest.TestCase):
    def test_large_calf_and_unchanged_rebuild(self):
        with np.load(Path(__file__).parents[1]/'fixtures/stacking_large_calf.npz') as data:
            domains = [calf_domain(data, '76', 'a'), calf_domain(data, '49', 'b')]
        with NativeStackEngine() as engine:
            engine.submit(domains, replace(config(), displacement=2.), 1); report = wait(engine)
            self.assertEqual(report['stacking']['status'], 'complete', report['stacking'])
            outputs = engine.surfaces(); cover = outputs[domains[1].key]
            delta = np.linalg.norm(cover-domains[1].own, axis=1)
            self.assertGreater(delta.max(), .77)
            record = next(r for r in report['stacking']['domains'] if r['domain']['muscle'] == 'b')
            self.assertEqual(record['vector']['algorithm'], 'vector-localized-v1')
            self.assertEqual(record['vector']['contact_validated'], 1)
            np.testing.assert_array_equal(outputs[domains[0].key], domains[0].own)
            engine.submit(domains, replace(config(), displacement=2.), 2); wait(engine)
            np.testing.assert_array_equal(engine.surfaces()[domains[1].key], cover)
