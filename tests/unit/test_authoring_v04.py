"""Static authoring contracts independent of Blender RNA."""
import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
from core.authoring import schema, validation
from core.authoring.codec import digest
from core.authoring.storage import FileStore
from core.authoring.errors import AuthoringError
from core.authoring.model import Budget, Document, plain
from core.authoring import clipping, substrate, regions, requirements, migration, lowering, fitting, packages
from core.authoring.repository import DraftRepository


def fixture():
    old = json.loads((Path(__file__).parents[1]/'fixtures/authoring/02-upper-arm.json').read_text())
    return migration.migrate(old, {v['binding']['id']: v['binding']['id'] for v in old['targets'].values()})


def inventory():
    vertices = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
    triangles = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]
    geometry = dict(vertices=vertices, triangles=triangles, matrix=np.eye(4).tolist())
    ids = ['SCP_DEMO_'+k for k in ('origin', 'guide', 'insertion')]
    rows = [dict(instance_id=k, scp_id=k, has_surface=True, side='unknown') for k in ids]
    return dict(root_id='root', scene_id='scene', revision='one', reference_pose='demo_rest', instances=rows, controls=[], geometry={k: deepcopy(geometry) for k in ids})


class SchemaTests(unittest.TestCase):
    def test_pinned_and_closed(self):
        validation.document(fixture())
        schema.audit(schema.bundled('protocol', '0.4.0'))
        value = fixture()
        value['simulations'] = {}
        with self.assertRaises(AuthoringError):
            validation.document(value)

    def test_unresolved_document_is_valid(self):
        value = fixture()
        del value['skeleton_profiles']['default']['bindings']['origin']['instance_id']
        validation.document(value)
        result = requirements.RequirementResolver(value, inventory()).resolve('/skeleton_profiles/default/bindings/origin')
        self.assertEqual(result['state'], 'unbound')

    def test_immutable_domain(self):
        value = Document.read(fixture())
        with self.assertRaises(TypeError):
            value.content['revision'] = 5
        self.assertEqual(plain(value.content), fixture())
        entity = value.records('entities')[0]
        self.assertEqual(entity.side, 'left')
        with self.assertRaises(TypeError):
            entity.evidence['note'] = 'Mutable'

    def test_ir_is_legacy_valid(self):
        output = lowering.compile_document(fixture(), inventory())
        validation.document(output['document'])
        self.assertEqual(output['version'], 'native_ir.v1')

    def test_motion_rejected(self):
        value = fixture()
        value['evaluation_profiles']['static']['joint_coordinates'] = []
        with self.assertRaises(AuthoringError):
            validation.document(value)


class RegionTests(unittest.TestCase):
    def test_landmark_frame_and_patch_use_declared_points(self):
        value, data = fixture(), inventory()
        profile = value['skeleton_profiles']['default']
        base = '/skeleton_profiles/default/'
        proof = profile['frames']['origin']['evidence']
        profile['landmarks'] = {k: dict(frame=base+'frames/origin', q=q, evidence=proof) for k, q in [('o',[0,0,0]), ('x',[0,1,0]), ('y',[0,0,1])]}
        profile['frames']['landmark'] = dict(kind='landmark_box', owner=base+'bindings/origin', origin=base+'landmarks/o', axis_point=base+'landmarks/x', plane_point=base+'landmarks/y', axis_labels=['a','b','c'], evidence=proof)
        validation.document(value)
        axes = substrate.frame_spec(value, data, base+'frames/landmark')['axes']
        np.testing.assert_allclose(axes, [[0,1,0], [0,0,1], [1,0,0]])
        profile['landmarks']['o']['frame'] = base+'frames/landmark'
        with self.assertRaises(AuthoringError):
            substrate.frame(value, data, base+'frames/landmark')

    def test_subtriangle_box(self):
        triangle = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float)
        selected, rejected = clipping.partition([triangle], clipping.box_planes([1, 1, -1], [2, 2, 1]), Budget())
        self.assertAlmostEqual(sum(map(clipping.area, selected)), 1)
        self.assertAlmostEqual(sum(map(clipping.area, selected+rejected)), 50)
        self.assertEqual(triangle.tolist(), [[0, 0, 0], [10, 0, 0], [0, 10, 0]])

    def test_retessellation(self):
        triangle = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float)
        planes = clipping.box_planes([1, 1, -1], [2, 2, 1])
        a, _ = clipping.partition([triangle], planes, Budget())
        b, _ = clipping.partition(clipping.subdivide(triangle), planes, Budget())
        self.assertAlmostEqual(sum(map(clipping.area, a)), sum(map(clipping.area, b)))

    def test_boolean_area(self):
        evaluator = regions.RegionEvaluator({}, {})
        triangle = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float)
        boxes = [dict(kind='selector', selector=dict(kind='box', low=[x, 1, -1], high=[x+2, 3, 1])) for x in (1, 2)]
        for kind, area in [('union', 6), ('intersection', 2), ('difference', 2)]:
            selected, _ = evaluator.partition([triangle], dict(kind=kind, operands=boxes), {})
            self.assertAlmostEqual(sum(map(clipping.area, selected)), area)

    def test_curved_sampling_budget(self):
        evaluator = regions.RegionEvaluator({}, {}, Budget(maximum=1))
        with self.assertRaises(AuthoringError):
            evaluator.selector([np.eye(3)], dict(kind='ellipsoid', center=[0, 0, 0], radii=[1, 1, 1], depth=4))

    def test_guide_reversal_requires_rebind(self):
        document = dict(controls=dict(g=dict(instance_id='g', kind='guide', reference_digest='old')))
        with self.assertRaises(AuthoringError) as error:
            substrate.control(document, dict(controls=[dict(instance_id='g', kind='guide', digest='new')]), '/controls/g')
        self.assertEqual(error.exception.code, 'CONTROL_REBIND_REQUIRED')

    def test_disconnected_seed(self):
        polygons = [np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]), np.array([[2, 0, 0], [3, 0, 0], [2, 1, 0]])]
        self.assertEqual(len(clipping.connected(polygons, [.1, .1, 0], 1e-6)), 1)


class RequirementTests(unittest.TestCase):
    def test_review_invalidates_when_bound_geometry_changes(self):
        from core.authoring.reviews import inputs
        value, data = fixture(), inventory()
        reference = '/skeleton_profiles/default/regions/origin'
        stamp = inputs(value, data, reference)
        value['reviews'] = dict(placement=dict(subject=reference, input_digest=stamp, state='accepted', note='Test reviewer'))
        self.assertEqual(requirements.review_state(value, reference, data), 'accepted')
        data['geometry']['SCP_DEMO_origin']['vertices'][0][0] += .01
        self.assertEqual(requirements.review_state(value, reference, data), 'stale')

    def test_undefined_not_absence(self):
        result = requirements.RequirementResolver({}, {}).resolve('/landmarks/spine')
        self.assertEqual(result['state'], 'undefined')
        self.assertEqual(result['code'], 'REFERENCE_UNDEFINED')

    def test_cycle_has_cause_path(self):
        result = requirements.RequirementResolver(dict(a=dict(x='/a/y', y='/a/x')), {}).resolve('/a/x')
        self.assertNotEqual(result['state'], 'resolved')
        self.assertGreater(len(result['causes'][0]), 2)

    def test_duplicate_instance_ambiguous(self):
        data = inventory()
        data['instances'].append(data['instances'][0])
        result = requirements.RequirementResolver(fixture(), data).resolve('/skeleton_profiles/default/bindings/origin')
        self.assertEqual(result['state'], 'ambiguous')

    def test_unknown_side_is_not_midline(self):
        self.assertEqual(inventory()['instances'][0]['side'], 'unknown')


class PersistenceTests(unittest.TestCase):
    def test_receipt_committed_with_draft(self):
        with TemporaryDirectory() as folder:
            repo = DraftRepository(FileStore(folder), 'scene')
            record, receipt = repo.commit('doc', 0, fixture(), dict(request_id='q'), 's')
            reopened = DraftRepository(FileStore(folder), 'scene')
            self.assertEqual(reopened.get('doc')['receipts']['q'], receipt)
            same, _ = reopened.commit('doc', 0, fixture(), dict(request_id='q'), 's')
            self.assertEqual(same['draft_revision'], 1)

    def test_reused_request_rejected(self):
        with TemporaryDirectory() as folder:
            repo = DraftRepository(FileStore(folder), 'scene')
            repo.commit('doc', 0, fixture(), dict(request_id='q'), 's')
            with self.assertRaises(AuthoringError):
                repo.commit('doc', 1, fixture(), dict(request_id='q', other=True), 's')

    def test_package_hash_verified(self):
        import hashlib
        with TemporaryDirectory() as folder:
            raw = json.dumps(fixture()).encode()
            Path(folder, 'package.json').write_bytes(raw)
            entry = dict(path='package.json', document_id=fixture()['document_id'], version='0.4.0', sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(packages.load_package(entry, folder)[0], fixture())
            entry['sha256'] = '0'*64
            with self.assertRaises(AuthoringError):
                packages.load_package(entry, folder)


if __name__ == '__main__':
    unittest.main()
