"""Reference corruption, identity and method selection must fail closed."""
import sys
from pathlib import Path
import numpy as np
import unittest
import tempfile
import base64
import io
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.deformation.reference import DeformationReference, DeformationSettings, SCHEMA, CAPABILITY
from core.deformation.serialization import encode, decode
from core.deformation.validation import validate_mesh_identity, validate_anatomy


def reference():
    points = np.array([[0.,0.,0.], [1.,0.,0.], [0.,1.,0.], [0.,0.,1.]])
    arrays = dict(vertices=points, quads=np.array([[0,1,2,3]]), vertex_ids=np.arange(4),
        proxy_vertices=points, proxy_tets=np.array([[0,1,2,3]]), samples=points,
        sample_weights=np.full(4,.25), sample_owners=np.zeros(4,np.int32), sample_addresses=np.arange(4))
    return DeformationReference(arrays, dict(schema=SCHEMA, capability=CAPABILITY,
        contributors=[dict(key="bone", vertex_count=4)]))


class DeformationReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_roundtrip_without_draft_or_external_files(self):
        initial = reference(); restored = decode(encode(initial))
        assert restored.signature == initial.signature
        for key in initial.arrays: np.testing.assert_array_equal(initial.arrays[key], restored.arrays[key])
        with self.assertRaises(ValueError): restored.arrays["vertices"][0,0] = 1
        with self.assertRaises(ValueError): restored.arrays["vertices"].flags.writeable = True
        with self.assertRaises(TypeError): restored.metadata["contributors"][0]["key"] = "changed"

    def test_checksum_rejects_finite_tampered_archive(self):
        payload = base64.b64decode(encode(reference()))
        with np.load(io.BytesIO(payload),allow_pickle=False) as archive: arrays = dict(archive)
        arrays["vertices"][0,0] += .1
        stream = io.BytesIO(); np.savez_compressed(stream,**arrays)
        with self.assertRaisesRegex(ValueError,"checksum"):
            decode(base64.b64encode(stream.getvalue()).decode())


    def test_bad_identity_and_nonfinite_positions(self):
        ref = reference(); a = ref.arrays
        with self.assertRaisesRegex(ValueError, "identities"):
            validate_mesh_identity(ref,a["vertices"],a["quads"],np.arange(4)[::-1])
        with self.assertRaisesRegex(ValueError, "connectivity"):
            validate_mesh_identity(ref,a["vertices"],a["quads"][:,::-1],a["vertex_ids"])
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            validate_mesh_identity(ref,np.full((4,3),np.nan),a["quads"],a["vertex_ids"])


    def test_incompatible_material_addresses_and_contributor_removal(self):
        ref = reference(); rows = ref.metadata["contributors"]
        with self.assertRaisesRegex(ValueError, "identities"):
            validate_anatomy(ref,[],{})
        with self.assertRaisesRegex(ValueError, "address"):
            validate_anatomy(ref,rows,{"bone":np.zeros((3,3))})
        target = ref.arrays["samples"] + [0.1,0.2,0.3]
        np.testing.assert_array_equal(validate_anatomy(ref,rows,{"bone":target}),target)


    def test_reference_detects_corruption_and_schema_change(self):
        ref = reference()
        with self.assertRaisesRegex(ValueError, "version"):
            DeformationReference(ref.arrays,dict(ref.metadata,schema=99))
        with self.assertRaises(ValueError): decode(encode(ref)[:-11])
        bad = dict(ref.arrays, proxy_tets=np.array([[0,1,2,500]]))
        with self.assertRaisesRegex(ValueError, "addresses"):
            DeformationReference(bad,ref.metadata)


    def test_native_le_identity_translation_and_reference_reset(self):
        tmp_path = Path(self.temporary.name)
        from core.deformation.native import PreparedSolver
        ref = reference()
        with PreparedSolver(ref,DeformationSettings(),tmp_path/"cancel") as solver:
            identity, _, _ = solver.solve(ref.arrays["samples"])
            moved, _, _ = solver.solve(ref.arrays["samples"]+[.03,-.02,.01])
            reset, _, _ = solver.solve(ref.arrays["samples"])
            ids, weights = solver.embedding()
        np.testing.assert_allclose(identity,ref.arrays["vertices"],atol=1e-10)
        np.testing.assert_allclose(moved,ref.arrays["vertices"]+[.03,-.02,.01],atol=1e-8)
        np.testing.assert_array_equal(reset,identity)
        np.testing.assert_allclose((ref.arrays["proxy_vertices"][ids]*weights[:,:,None]).sum(1),identity,atol=1e-10)


    def test_native_cancel_and_unknown_strategy(self):
        tmp_path = Path(self.temporary.name)
        from core.deformation.native import PreparedSolver
        path = tmp_path/"cancel"; path.touch()
        with PreparedSolver(reference(),DeformationSettings(),path) as solver:
            with self.assertRaisesRegex(RuntimeError, "CANCELLED"): solver.solve(reference().arrays["samples"])
        with self.assertRaisesRegex(ValueError, "fallback"):
            PreparedSolver(reference(),DeformationSettings(method="OTHER"),path)
