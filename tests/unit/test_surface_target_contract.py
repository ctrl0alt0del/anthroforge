from types import SimpleNamespace
import unittest

from tests._support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core.vcp.surface_binding_codec import (
    decode_binding_envelope, encode_binding_envelope, remap_binding_target, require_matching_envelope,
)
from core.vcp.surface_target import (
    SurfaceRole, SurfaceTargetKind, effective_tissue_target, target_ref, target_ref_errors,
)
from core.visualization.surface_target_service import SurfaceTargetService
from core.vcp.attachment_backend import triangulated_topology_signature


class _FakeProvider:
    kind = SurfaceTargetKind.MUSCLE

    def __init__(self, result):
        self.result = result

    def resolve(self, root, scene, target, runtime):
        return self.result, root, scene, target, runtime


class SurfaceTargetContractTests(unittest.TestCase):
    def test_contract_rejects_role_from_another_target_kind(self):
        ref = target_ref("SCP", "S1", "MUSCLE_INFL")
        self.assertIn("MUSCLE_INFL is invalid for SCP.", target_ref_errors(ref))

    def test_legacy_tissue_resolves_through_scp_compatibility(self):
        tissue = SimpleNamespace(schema_version=1, host_scp_id="S1")
        self.assertEqual(effective_tissue_target(tissue), target_ref("SCP", "S1", "SCP_GEOMETRY"))

    def test_schema_two_uses_only_generic_target_fields(self):
        tissue = SimpleNamespace(schema_version=2, host_scp_id="OLD", attachment_target_type="MUSCLE",
                                 attachment_target_id="M1", attachment_target_surface="MUSCLE_INFL")
        self.assertEqual(effective_tissue_target(tissue), target_ref("MUSCLE", "M1", "MUSCLE_INFL"))

    def test_provider_is_injected_and_substitutable(self):
        ref, result = target_ref("MUSCLE", "M1", "MUSCLE_BASE"), object()
        resolved = SurfaceTargetService((_FakeProvider(result),)).resolve("root", "scene", ref, "runtime")
        self.assertEqual(resolved, (result, "root", "scene", ref, "runtime"))

    def test_version_three_envelope_detects_identity_mismatch(self):
        ref = target_ref("MUSCLE", "M1", "MUSCLE_INFL")
        raw = encode_binding_envelope(ref, "TOPO", ({"raw": "X"},))
        envelope = decode_binding_envelope(raw)
        with self.assertRaisesRegex(ValueError, "identity"):
            require_matching_envelope(envelope, target_ref("MUSCLE", "M2", "MUSCLE_INFL"), "TOPO")

    def test_import_remaps_target_embedded_in_envelope(self):
        ref = target_ref("MUSCLE", "OLD", "MUSCLE_INFL")
        raw = encode_binding_envelope(ref, "TOPO", ())
        mapped = decode_binding_envelope(remap_binding_target(raw, "MUSCLE", "OLD", "NEW"))
        self.assertEqual(mapped.target.entity_id, "NEW")

    def test_triangle_winding_is_part_of_topology_identity(self):
        first = triangulated_topology_signature(3, ((0, 1, 2),))
        reversed_winding = triangulated_topology_signature(3, ((0, 2, 1),))
        self.assertNotEqual(first, reversed_winding)

    def test_coordinate_changes_cannot_affect_topology_identity(self):
        first = triangulated_topology_signature(4, ((0, 1, 2), (0, 2, 3)))
        deformed = triangulated_topology_signature(4, ((0, 1, 2), (0, 2, 3)))
        self.assertEqual(first, deformed)


if __name__ == "__main__":
    unittest.main()
