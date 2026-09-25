import unittest
import numpy as np
from core.authoring.attachment_footprint import patch, one_boundary
from core.authoring.attachment_graft_native import calculate
from core.authoring.errors import AuthoringError


def square():
    geometry = dict(vertices=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                    triangles=[[0, 1, 2], [0, 2, 3]], matrix=np.eye(4).tolist())
    records = [dict(tri_vidx=t, polygon=np.eye(3).tolist()) for t in geometry['triangles']]
    return geometry, records


class AttachmentGraftTests(unittest.TestCase):
    def test_duplicate_region_records_and_deformed_indexed_identity(self):
        geometry, records = square(); geometry['vertices'][2] = [1.13, .72, .09]
        v, f, loop = patch(geometry, records+records)
        self.assertEqual((len(v), len(f), len(loop)), (4, 2, 4))
        np.testing.assert_equal(v, geometry['vertices'])
        records[0]['tri_vidx'] = [float(i) for i in records[0]['tri_vidx']]
        np.testing.assert_equal(patch(geometry, records)[0], v)

    def test_invalid_triangle_and_barycentrics_rejected(self):
        geometry, records = square(); records[0]['tri_vidx'] = [0, 1, 3]
        with self.assertRaises(AuthoringError): patch(geometry, records)
        geometry, records = square(); records[0]['polygon'][0] = [2, -1, 0]
        with self.assertRaises(AuthoringError): patch(geometry, records)

    def test_disconnected_boundaries_rejected(self):
        with self.assertRaises(AuthoringError): one_boundary(np.array([[0, 1, 2], [3, 4, 5]]))

    def test_native_correspondence_survives_reversed_shifted_loop(self):
        a = np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], float)
        b = np.roll(a[::-1]+[0, 0, 2], 1, axis=0); n = np.tile([0, 0, 1.], (4, 1))
        axes = [[1, 0, 0], [0, 1, 0]]*2
        result, order = calculate(a, b, n, axes, .2)
        self.assertTrue(np.isfinite(result).all()); self.assertEqual(result.shape, (96, 3))
        np.testing.assert_allclose(result.reshape(24, 4, 3)[:, :, :2], np.tile(a[:, :2], (24, 1, 1)))
        np.testing.assert_equal(calculate(a, b, n, axes, .2)[0], result)
        self.assertEqual(order[1], -1)

    def test_native_malformed_buffers_rejected(self):
        a = np.zeros((4, 3)); axes = np.zeros((4, 3))
        with self.assertRaises(AuthoringError): calculate(a, a[:2], a, axes, .2)
        with self.assertRaises(AuthoringError): calculate(a*np.nan, a, a, axes, .2)
