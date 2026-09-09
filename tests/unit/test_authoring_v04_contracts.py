"""Provider, material correspondence and package contracts."""
import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from test_authoring_v04 import fixture, inventory
from core.authoring.errors import AuthoringError
from core.authoring import candidates, substrate, packages, lowering, references
from core.authoring.model import Budget


class ProviderContracts(unittest.TestCase):
    def test_provider_result_contract(self):
        value = fixture()
        context = dict(document=value, inventory=inventory())
        frame = value['skeleton_profiles']['default']['frames']['origin']
        definition = dict(proposal=dict(kind='frame', value=frame))
        cases = [(candidates.AuthoredDefinition(), dict(need='frame'), definition), (candidates.ConstructionRule(), dict(need='frame'), definition), (candidates.ExistingControl(), dict(need='binding', target='/skeleton_profiles/default/bindings/origin'), dict(instance_id='SCP_DEMO_origin'))]
        for provider, requirement, params in cases:
            self.assertEqual(provider.preflight(context, requirement, params), [])
            rows = provider.propose(context, requirement, params, Budget())
            self.assertTrue(rows)
            self.assertTrue(all(set(row) == {'proposal', 'inputs', 'approximations'} for row in rows))

    def test_incomplete_is_distinct_from_empty(self):
        provider = candidates.ExistingControl()
        requirement = dict(need='binding', target='/skeleton_profiles/default/bindings/missing')
        self.assertTrue(provider.preflight(dict(document=fixture()), requirement, {}))
        requirement['target'] = '/skeleton_profiles/default/bindings/origin'
        rows = provider.propose(dict(document=fixture(), inventory=inventory()), requirement, dict(instance_id='not-present'), Budget())
        self.assertEqual(rows, [])

    def test_cancelled_provider_does_not_produce_output(self):
        with self.assertRaises(AuthoringError) as error:
            candidates.AuthoredDefinition().propose({}, {}, dict(proposal=dict(kind='frame', value={})), Budget(cancelled=True))
        self.assertEqual(error.exception.code, 'CANCELLED')


class MaterialContracts(unittest.TestCase):
    def test_reference_material_parameter_survives_stretch(self):
        row = dict(reference_points=[[0,0,0],[1,0,0],[4,0,0]], points=[[0,0,0],[2,1,0],[8,0,0]])
        np.testing.assert_allclose(substrate.guide_position(row, .25), [2,1,0])
        material, distance = substrate.guide_material(np.array(row['points']), np.array([2,1,0]), row['reference_points'])
        self.assertAlmostEqual(material, .25)
        self.assertAlmostEqual(distance, 0)

    def test_reversal_is_not_compatible_deformation(self):
        spec = dict(kind='guide', reference_digest='old', reference_points=[[0,0,0],[1,0,0]])
        substrate.validate_control(spec, dict(digest='new', points=[[0,0,0],[2,0,0]]))
        with self.assertRaises(AuthoringError):
            substrate.validate_control(spec, dict(digest='new', points=[[2,0,0],[0,0,0]]))

    def test_array_references_and_precise_prefixes(self):
        self.assertEqual(references.lookup(dict(a=[dict(x=3)]), '/a/0/x'), 3)
        self.assertFalse(references.within('/entities/arm', '/entities/a'))


class PackageContracts(unittest.TestCase):
    def test_imported_native_evidence_and_ir(self):
        value = fixture()
        library = {k: deepcopy(value[k]) for k in ('dsl','version','document_id','revision','kind','sources','concepts','recipes','shape_presets','policies')}
        library.update(document_id='shared', kind='library')
        with TemporaryDirectory() as folder:
            raw = json.dumps(library).encode()
            Path(folder, 'library.json').write_bytes(raw)
            value['imports'] = dict(shared=dict(path='library.json', document_id='shared', version='0.4.0', sha256=hashlib.sha256(raw).hexdigest()))
            for key, group in [('recipe','recipes'),('shape','shape_presets'),('policy','policies')]:
                instance = value['instances']['example_muscle']
                instance[key] = 'shared#'+instance[key]
                value[group] = {}
            result = packages.expand(value, folder)
            self.assertEqual(lowering.compile_document(result, inventory())['version'], 'native_ir.v1')

    def test_package_cannot_escape_root(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(AuthoringError) as error:
                packages.load_package(dict(path='../outside.json'), folder)
            self.assertEqual(error.exception.code, 'PACKAGE_PATH_ESCAPE')


if __name__ == '__main__':
    unittest.main()
