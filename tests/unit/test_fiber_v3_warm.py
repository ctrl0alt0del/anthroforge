from types import SimpleNamespace
import unittest

import numpy as np

from core.vcp.v3.warm import (clear_v3_warm_states, prepare_v3_warm_seed,
                              store_v3_warm_state, v3_warm_cache_stats)


def _anchors(y=0.0, owner="S"):
    return tuple(SimpleNamespace(point=(float(x), float(y), 0.0), owner_id=owner)
                 for x in (0.0, 1.0, 2.0))


def _points():
    return ((0, 0, 0), (.5, 1, 0), (1, 0, 0), (1.5, -1, 0), (2, 0, 0))


def _loop_points():
    return ((0, 0, 0), (.5, 1, 0), (1, 0, 0), (1, -1, 0), (0, -1, 0), (-.5, 0, 0))


class FiberV3WarmTests(unittest.TestCase):
    def setUp(self):
        clear_v3_warm_states()

    def tearDown(self):
        clear_v3_warm_states()

    def test_same_layout_reuses_interior_and_restores_new_pins(self):
        key = ("scene", "root", "uid", "F")
        self.assertTrue(store_v3_warm_state(key, _points(), (0, 2, 4), _anchors(), "v3", "abi"))
        seed = prepare_v3_warm_seed(key, True, 5, _anchors(.25), "v3", "abi")
        self.assertEqual((seed[1], seed[3]), (_points()[1], _points()[3]))
        self.assertEqual(tuple(row[1] for row in seed[::2]), (.25, .25, .25))

    def test_node_count_change_resamples_each_hard_pin_span(self):
        key = ("scene", "root", "uid", "F")
        store_v3_warm_state(key, _points(), (0, 2, 4), _anchors(), "v3", "abi")
        seed = prepare_v3_warm_seed(key, True, 9, _anchors(.1), "v3", "abi")
        self.assertEqual(len(seed), 9)
        np.testing.assert_allclose(np.asarray(seed)[[0, 4, 8], 1], .1)

    def test_incompatible_owner_or_backend_is_a_cold_miss(self):
        key = ("scene", "root", "uid", "F")
        store_v3_warm_state(key, _points(), (0, 2, 4), _anchors(), "v3", "abi")
        self.assertFalse(prepare_v3_warm_seed(key, True, 5, _anchors(owner="X"), "v3", "abi"))
        self.assertFalse(prepare_v3_warm_seed(key, True, 5, _anchors(), "v3", "new-abi"))
        self.assertEqual(v3_warm_cache_stats()["misses"], 2)

    def test_scoped_clear_preserves_other_fibers(self):
        keys = (("scene", "root", "a", "A"), ("scene", "root", "b", "B"))
        for key in keys: store_v3_warm_state(key, _points(), (0, 2, 4), _anchors(), "v3", "abi")
        clear_v3_warm_states("scene", "root", {"A"})
        self.assertFalse(prepare_v3_warm_seed(keys[0], True, 5, _anchors(), "v3", "abi"))
        self.assertTrue(prepare_v3_warm_seed(keys[1], True, 5, _anchors(), "v3", "abi"))

    def test_cyclic_state_preserves_closing_span_and_exact_count(self):
        key = ("scene", "root", "loop", "L"); points = _loop_points()
        self.assertTrue(store_v3_warm_state(key, points, (0, 2, 4), _anchors(),
                                           "v3", "abi", cyclic=True))
        seed = prepare_v3_warm_seed(key, True, 12, _anchors(.25), "v3", "abi", cyclic=True)
        self.assertEqual(len(seed), 12)
        self.assertEqual(tuple(seed[index][1] for index in (0, 3, 6)), (.25, .25, .25))
        self.assertFalse(np.array_equal(seed[0], seed[-1]))

    def test_open_and_cyclic_warm_states_are_incompatible(self):
        key = ("scene", "root", "loop", "L")
        store_v3_warm_state(key, _loop_points(), (0, 2, 4), _anchors(),
                            "v3", "abi", cyclic=True)
        self.assertFalse(prepare_v3_warm_seed(key, True, 6, _anchors(), "v3", "abi"))


if __name__ == "__main__":
    unittest.main()
