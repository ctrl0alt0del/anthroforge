import unittest
from dataclasses import replace

from core.vcp.soft_tissue_attachment import (
    AttachmentError,
    AttachmentTopologyError,
    SurfaceMesh,
    apply_surface_attachment,
    capture_surface_binding,
    resolve_surface_binding,
)
from core.vcp.soft_tissue_model import (
    AttachmentMode,
    AttachmentSpec,
    TargetKind,
    TargetSurface,
    validate_model,
)
from tools.prototype_soft_tissue_models import abdominal_pad_model


class SoftTissueAttachmentTests(unittest.TestCase):
    def test_public_attachment_modes_exclude_sliding(self):
        self.assertEqual({item.value for item in AttachmentMode}, {"FREE", "FIXED", "SOFT"})

    def test_surface_target_kinds_include_muscle(self):
        self.assertEqual({item.value for item in TargetKind}, {"NONE", "SCP", "MUSCLE"})

    def test_barycentric_binding_preserves_normal_offset(self):
        binding = capture_surface_binding(_single_triangle(), _scp_attachment(), (0.25, 0.25, 0.1))
        self.assertEqual(binding.tri_weights, (0.5, 0.25, 0.25))
        self.assertEqual(resolve_surface_binding(_single_triangle(), binding), (0.25, 0.25, 0.1))

    def test_binding_follows_deformed_target_triangle(self):
        binding = capture_surface_binding(_single_triangle(), _scp_attachment(), (0.25, 0.25, 0.1))
        deformed = _surface(((0, 0, 1), (2, 0, 1), (0, 2, 1)), ((0, 1, 2),))
        self.assertEqual(resolve_surface_binding(deformed, binding), (0.5, 0.5, 1.1))

    def test_topology_change_invalidates_binding(self):
        binding = capture_surface_binding(_single_triangle(), _scp_attachment(), (0.25, 0.25, 0.1))
        changed = _surface(((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)), ((0, 1, 2), (1, 3, 2)))
        with self.assertRaisesRegex(AttachmentTopologyError, "topology changed"):
            resolve_surface_binding(changed, binding)

    def test_wrong_target_surface_is_rejected(self):
        binding = capture_surface_binding(_single_triangle(), _scp_attachment(), (0.25, 0.25, 0.1))
        wrong = _surface(((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 1, 2),), "SCP_OTHER")
        with self.assertRaisesRegex(AttachmentError, "does not match"):
            resolve_surface_binding(wrong, binding)

    def test_soft_attachment_blends_toward_surface(self):
        attachment = replace(_scp_attachment(), mode=AttachmentMode.SOFT, strength=0.25)
        binding = capture_surface_binding(_single_triangle(), attachment, (0.25, 0.25, 0.1))
        result = apply_surface_attachment(_single_triangle(), attachment, binding, (0.25, 0.25, 0.5))
        self.assertEqual(result.point, (0.25, 0.25, 0.4))

    def test_prototype_contains_only_scp_target(self):
        model = abdominal_pad_model()
        targets = {(item.target_kind, item.target_surface) for item in model.attachments}
        self.assertEqual(targets, {(TargetKind.SCP, TargetSurface.SCP_GEOMETRY)})
        self.assertEqual(validate_model(model), ())


def _single_triangle():
    return _surface(((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 1, 2),))


def _square_surface():
    vertices = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0))
    return _surface(vertices, ((0, 1, 2), (1, 3, 2)))


def _surface(vertices, triangles, target_id="SCP_TEST"):
    return SurfaceMesh(
        TargetKind.SCP, target_id, TargetSurface.SCP_GEOMETRY,
        tuple(vertices), tuple(triangles),
    )


def _scp_attachment():
    return AttachmentSpec(
        TargetKind.SCP, "SCP_TEST", TargetSurface.SCP_GEOMETRY,
        AttachmentMode.FIXED, 1.0, "AF_ST_ATTACH", 0.1,
    )


if __name__ == "__main__":
    unittest.main()
