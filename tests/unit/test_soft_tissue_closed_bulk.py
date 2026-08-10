import unittest
from dataclasses import replace

from core.vcp.soft_tissue_closed_bulk import (
    LegacyBlobSpec,
    closed_bulk_model_from_legacy,
    legacy_spec_from_closed_bulk,
)
from core.vcp.soft_tissue_model import (
    AttachmentMode,
    AttachmentSpec,
    BaseDomain,
    TargetKind,
    TargetSurface,
)


class SoftTissueClosedBulkTests(unittest.TestCase):
    def test_sphere_maps_to_point_based_closed_bulk(self):
        legacy = LegacyBlobSpec("BLOB_1", "Sphere", sag_strength=0.35)
        model = closed_bulk_model_from_legacy(legacy)
        self.assertEqual(model.base.domain, BaseDomain.POINT)
        self.assertEqual(model.inflation.scale, (1.0, 1.0, 1.0))
        self.assertAlmostEqual(model.relaxation.sagginess, 0.035)

    def test_ellipsoid_controls_round_trip_exactly(self):
        attachment = AttachmentSpec(TargetKind.SCP, "SCP_1", TargetSurface.SCP_GEOMETRY,
                                    AttachmentMode.FIXED, 1.0)
        legacy = LegacyBlobSpec("BLOB_2", "Ellipsoid", (1.0, 2.0, 3.0), 0.7, "ELLIPSOID",
                                (1.2, 0.8, 1.5), 64, (0.0, -1.0, 0.0), 2.5, 0.4, 0.6, 50, attachment)
        restored = legacy_spec_from_closed_bulk(closed_bulk_model_from_legacy(legacy))
        self.assertEqual(restored, legacy)

    def test_sphere_canonicalizes_unused_axis_scale(self):
        legacy = LegacyBlobSpec("BLOB_3", "Sphere", shape="SPHERE", axis_scale=(2.0, 3.0, 4.0))
        restored = legacy_spec_from_closed_bulk(closed_bulk_model_from_legacy(legacy))
        self.assertEqual(restored.axis_scale, (1.0, 1.0, 1.0))

    def test_legacy_sag_above_property_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sag parameters"):
            closed_bulk_model_from_legacy(LegacyBlobSpec("BLOB_4", "Invalid", sag_strength=10.1))

    def test_non_point_model_cannot_migrate_to_blob(self):
        model = closed_bulk_model_from_legacy(LegacyBlobSpec("BLOB_5", "Bulk"))
        with self.assertRaisesRegex(ValueError, "point base"):
            legacy_spec_from_closed_bulk(replace(model, base=replace(model.base, domain=BaseDomain.SURFACE,
                                                                     reference="surface")))


if __name__ == "__main__":
    unittest.main()
