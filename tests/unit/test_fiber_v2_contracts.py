import ast
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from core.vcp.v2 import (
    V2_CONTRACT_VERSION, V2_ENGINE_VERSION, V2Anchor, V2AnchorRole,
    V2ColliderSnapshot, V2CollisionPolicy, V2Diagnostics, V2Request,
    V2ResolvedTolerances, V2Result, V2Settings, V2Termination,
    decode_request, decode_result, encode_contract,
)


def _collider(generation=("mesh-1",)):
    return V2ColliderSnapshot("CRANIUM", "SCP_1",
                              ((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                              ((0, 1, 2),), generation)


def _request(token=7, warm_seed=()):
    anchors = (V2Anchor((0, 0, 0), "SCP_1", V2AnchorRole.ENDPOINT_A, 0),
               V2Anchor((1, 0, 0), "SCP_2", V2AnchorRole.ENDPOINT_B, 1))
    return V2Request(token, "scene-1", "root-1", "revision-4", V2Settings(),
                     V2ResolvedTolerances(), V2CollisionPolicy(), anchors,
                     (_collider(),), warm_seed=warm_seed)


def _result(request):
    diagnostics = V2Diagnostics(stationarity_residual=1.0e-7, accepted_steps=4)
    return V2Result(request.signature(), V2Termination.CONVERGED,
                    ((0, 0, 0), (1, 0, 0)), diagnostics, validated=True,
                    route_branch="DIRECT", backend_version="native-1")


class FiberV2ContractTests(unittest.TestCase):
    def test_request_json_round_trip_is_lossless(self):
        request = _request(warm_seed=((0, 0, 0), (1, 0, 0)))
        decoded = decode_request(encode_contract(request))
        self.assertEqual(decoded, request)
        self.assertEqual(decoded.signature(), request.signature())

    def test_result_json_round_trip_is_lossless(self):
        result = _result(_request())
        decoded = decode_result(encode_contract(result))
        self.assertEqual(decoded, result)
        self.assertTrue(decoded.successful)

    def test_signature_ignores_execution_token_and_warm_seed(self):
        base = _request()
        alternate = _request(token=99, warm_seed=((9, 8, 7),))
        self.assertEqual(base.signature(), alternate.signature())

    def test_signature_covers_solution_defining_fields(self):
        request = _request()
        variants = (replace(request, source_revision="revision-5"),
                    replace(request, engine_version="fiber-v2-contract-3"),
                    replace(request, symmetry_mode="MIRROR"),
                    replace(request, settings=replace(request.settings, node_count=128)),
                    replace(request, colliders=(_collider(("mesh-2",)),)))
        self.assertTrue(all(item.signature() != request.signature() for item in variants))

    def test_signature_hashes_geometry_when_generation_is_absent(self):
        request = _request(); first = _collider(())
        second = replace(first, vertices=((0, 0, 0), (2, 0, 0), (0, 1, 0)))
        left = replace(request, colliders=(first,))
        right = replace(request, colliders=(second,))
        self.assertNotEqual(left.signature(), right.signature())

    def test_input_lists_are_copied_into_immutable_tuples(self):
        vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        collider = V2ColliderSnapshot("C", "S", vertices, [[0, 1, 2]])
        vertices[0][0] = 42
        self.assertEqual(collider.vertices[0], (0.0, 0.0, 0.0))
        with self.assertRaises(FrozenInstanceError):
            collider.owner_id = "CHANGED"

    def test_backend_unavailable_is_a_first_class_result(self):
        request = _request()
        result = V2Result(request.signature(), V2Termination.BACKEND_UNAVAILABLE,
                          (), V2Diagnostics(), message="DLL missing")
        self.assertFalse(result.successful)
        self.assertEqual(result.termination.value, "BACKEND_UNAVAILABLE")

    def test_contract_payload_is_stable_and_json_native(self):
        request = _request()
        first, second = encode_contract(request), encode_contract(request)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first)["contract_version"], V2_CONTRACT_VERSION)
        self.assertEqual(json.loads(first)["engine_version"], V2_ENGINE_VERSION)

    def test_invalid_numeric_values_are_rejected(self):
        with self.assertRaises(ValueError):
            V2Settings(node_count=0)
        with self.assertRaises(ValueError):
            V2CollisionPolicy(collision_radius=float("nan"))
        with self.assertRaises(ValueError):
            V2Diagnostics(ccd_step_fraction=1.1)

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            V2Anchor((0, 0), authored_index=0)
        with self.assertRaises(ValueError):
            V2ColliderSnapshot("C", "S", ((0, 0, 0),), ((0, 1, 0),))

    def test_unsupported_contract_versions_fail_closed(self):
        payload = json.loads(encode_contract(_request()))
        payload["contract_version"] = V2_CONTRACT_VERSION + 1
        with self.assertRaisesRegex(ValueError, "unsupported"):
            decode_request(payload)

    def test_v2_contract_package_has_no_blender_import(self):
        folder = Path(__file__).parents[2] / "core" / "vcp" / "v2"
        imports = [node.names[0].name for path in folder.glob("*.py")
                   for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                   if isinstance(node, (ast.Import, ast.ImportFrom)) and node.names]
        self.assertNotIn("bpy", imports)


if __name__ == "__main__":
    unittest.main()
