import unittest

from core.vcp.soft_tissue_attachment_feather import attachment_feather_weights


class SoftTissueAttachmentFeatherTests(unittest.TestCase):
    def test_zero_feather_preserves_exact_binary_mask(self):
        vertices, faces = _strip_mesh()
        weights = attachment_feather_weights(vertices, faces, (0, 3), 0.0)
        self.assertEqual(weights, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))

    def test_feather_falls_smoothly_outward_from_core(self):
        vertices, faces = _strip_mesh()
        weights = attachment_feather_weights(vertices, faces, (0, 3), 1.0)
        self.assertGreater(weights[1], weights[2])
        self.assertGreater(weights[4], weights[5])
        self.assertTrue(0.0 < weights[2] < weights[1] < 1.0)

    def test_feather_does_not_jump_between_disconnected_surfaces(self):
        vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, .01), (1, 0, .01), (0, 1, .01))
        weights = attachment_feather_weights(vertices, ((0, 1, 2), (3, 4, 5)), (0,), 1.0)
        self.assertEqual(weights[3:], (0.0, 0.0, 0.0))


def _strip_mesh():
    vertices = ((0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0))
    faces = ((0, 1, 4, 3), (1, 2, 5, 4))
    return vertices, faces


if __name__ == "__main__":
    unittest.main()
