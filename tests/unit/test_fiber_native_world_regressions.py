"""Regression coverage for row-local clearance and active-world lifetime guards."""

import unittest

import numpy as np

from core.vcp.v2.collision_native import NativeCollisionWorld


VERTICES = np.asarray(((-2, -2, 0), (2, -2, 0), (0, 2, 0)), dtype=float)
FACES = np.asarray(((0, 1, 2),), dtype=np.int64)
POINTS = np.asarray(((0, 0, .01), (.1, 0, .01), (0, 0, .1), (.1, 0, .1)))
EDGES = np.asarray(((0, 1), (2, 3)), dtype=np.int64)


class NativeWorldRegressionTests(unittest.TestCase):
    def setUp(self):
        self.world, _ = NativeCollisionWorld.from_batch([VERTICES], [FACES], [1])
        self.addCleanup(self.world.close)

    def session(self):
        session = self.world.begin_v3_session([0], [0])
        self.addCleanup(session.close)
        return session

    def test_world_reports_each_edges_own_distance(self):
        result = self.world.validate(POINTS, EDGES, [0, 0], [0, 0], 0, .2)
        np.testing.assert_allclose(result[2], (.01, .1), atol=1e-12)
        self.assertAlmostEqual(result[3].minimum, .01)
        np.testing.assert_array_equal(result[0], (False, False))

    def test_instance_distances_are_independent_of_edge_order(self):
        forward = self.world.validate_instance(0, POINTS, EDGES, [0, 0], [0, 0], 0, .2)
        reverse = self.world.validate_instance(0, POINTS, EDGES[::-1], [0, 0], [0, 0], 0, .2)
        np.testing.assert_allclose(forward[2], (.01, .1), atol=1e-12)
        np.testing.assert_array_equal(forward[2], reverse[2][::-1])

    def test_indexed_parallel_validation_preserves_row_distances(self):
        edges = np.tile(EDGES, (256, 1)); owners = np.zeros(len(edges), dtype=np.int32)
        library = self.world.library; workers = library.af_fiber_worker_threads()
        self.addCleanup(library.af_fiber_set_worker_threads, workers)
        for count in (1, 2, 4):
            library.af_fiber_set_worker_threads(count)
            result = self.world.validate(POINTS, edges, owners, owners, 0, .2)
            np.testing.assert_allclose(result[2], np.tile((.01, .1), 256), atol=1e-12)

    def test_active_session_prevents_world_destruction(self):
        self.session(); handle = self.world.handle
        self.assertRaises(RuntimeError, self.world.close)
        self.assertEqual(self.world.handle, handle)

    def test_active_session_prevents_transform_and_refit(self):
        self.session()
        self.assertRaises(RuntimeError, self.world.update_transform, 0, np.eye(4))
        self.assertRaises(RuntimeError, self.world.update_vertices, [0], [VERTICES])

    def test_active_session_prevents_topology_mutation(self):
        self.session()
        self.assertRaises(RuntimeError, self.world.add, VERTICES, FACES, 2, 1, False)
        self.assertRaises(RuntimeError, self.world.commit)

    def test_world_remains_queryable_after_rejected_mutation(self):
        self.session()
        self.assertRaises(RuntimeError, self.world.update_vertices, [0], [VERTICES + 1])
        result = self.world.validate(POINTS, EDGES, [0, 0], [0, 0], 0, .2)
        np.testing.assert_allclose(result[2], (.01, .1), atol=1e-12)

    def test_world_becomes_mutable_only_after_last_session_closes(self):
        first, second = self.session(), self.session()
        first.close(); first.close()
        self.assertEqual(self.world._sessions, 1)
        self.assertRaises(RuntimeError, self.world.close)
        second.close()
        self.world.update_transform(0, np.eye(4))
        self.world.update_vertices([0], [VERTICES])
        self.world.add(VERTICES, FACES, 2, 1, False); self.world.commit()
        self.world.close(); self.world.close()
        self.assertIsNone(self.world.handle)


if __name__ == "__main__":
    unittest.main()
