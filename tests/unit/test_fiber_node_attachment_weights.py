import unittest

import numpy as np

from core.vcp.fiber_node_attachment_weights import attachment_owner_weights


def _chain(count=41):
    return np.column_stack((np.linspace(0, 1, count), np.zeros((count, 2))))


class AttachmentWeightTests(unittest.TestCase):
    def test_transition_is_local_bounded_and_partition_of_unity(self):
        owners = ['A'] * 21 + ['B'] * 20
        rows = attachment_owner_weights(_chain(), owners, (0, 40))
        weight = np.array([dict(row).get('B', 0) for row in rows])
        self.assertTrue(all(len(row) <= 2 and all(w > 0 for _, w in row) for row in rows))
        np.testing.assert_allclose([sum(w for _, w in row) for row in rows], 1)
        self.assertTrue(np.all(np.diff(weight) >= 0)); self.assertLess(np.max(np.diff(weight)), .1)
        self.assertEqual(rows[7], (('A', 1.0),)); self.assertEqual(rows[34], (('B', 1.0),))

    def test_authored_midpoint_is_exact_and_separates_spans(self):
        owners = ['A'] * 10 + ['B'] * 21 + ['C'] * 10
        rows = attachment_owner_weights(_chain(), owners, (0, 20, 40))
        self.assertEqual(rows[20], (('B', 1.0),))
        self.assertFalse(any('C' in dict(row) for row in rows[:20]))
        self.assertFalse(any('A' in dict(row) for row in rows[21:]))

    def test_cyclic_seam_is_blended_without_unpinning_anchor(self):
        theta = np.arange(40) * 2 * np.pi / 40
        points = np.column_stack((np.cos(theta), np.sin(theta), np.zeros(40)))
        owners = ['B'] * 8 + ['A'] * 25 + ['B'] * 7
        rows = attachment_owner_weights(points, owners, (20,), True)
        self.assertEqual(rows[20], (('A', 1.0),)); self.assertEqual(rows[0], (('B', 1.0),))
        self.assertTrue(any(len(row) == 2 for row in rows))

    def test_duplicate_reference_points_remain_finite(self):
        rows = attachment_owner_weights(np.zeros((5, 3)), ['A', 'A', 'B', 'B', 'B'], (0, 4))
        self.assertEqual(rows[0], (('A', 1.0),)); self.assertEqual(rows[-1], (('B', 1.0),))
        self.assertTrue(all(np.isfinite(w) for row in rows for _, w in row))

    def test_invalid_hard_pin_configuration_is_rejected(self):
        with self.assertRaises(ValueError): attachment_owner_weights(_chain(), ['A'] * 41, (1, 40))


if __name__ == '__main__': unittest.main()
