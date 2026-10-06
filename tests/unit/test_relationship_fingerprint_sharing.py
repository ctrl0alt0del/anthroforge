"""Shared bones retain exact, content-authoritative fingerprints across scans."""
import unittest
from dataclasses import replace
import numpy as np
from core.muscle_relationships import fingerprints as f
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.obstacles import Obstacle
from relationship_fixtures import fixture


class Fingerprints(unittest.TestCase):
    def test_shared_and_independent_bones_are_identical_and_rechecked(self):
        domains = fixture()
        bone = Obstacle(np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]), np.array([[0, 1, 2]]))
        shared = tuple(replace(d, obstacles=(bone,)) for d in domains)
        independent = tuple(replace(d, obstacles=(Obstacle(bone.vertices.copy(), bone.faces.copy()),)) for d in domains)
        before = f.manifest(shared, DetectionSettings())
        self.assertEqual(before, f.manifest(independent, DetectionSettings()))
        for d in shared: self.assertEqual(before['domains'][f.token(f.key(d))], f.domain_stamp(d))
        bone.vertices[0, 2] = .00000000001
        after = f.manifest(shared, DetectionSettings())
        self.assertEqual(len(f.changed(before, after)), len(shared))
        self.assertTrue(all(changes == ['obstacles'] for changes in f.changed(before, after).values()))


if __name__ == '__main__': unittest.main()
