"""Constraint contract through actual Blender authoring and persisted journals."""
import copy
import json
import tempfile
from pathlib import Path
import bpy
import numpy as np
import test_authoring_shape_transfer as legacy
from _helpers import BlenderTestCase, root
from _transfer_fixture import read_preview, message, fixture
from anthroforge.core.authoring.codec import digest
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene


class TransferConstraintTests(BlenderTestCase):
    send = legacy.ShapeTransferTests.send
    preview = legacy.ShapeTransferTests.preview

    def setUp(self):
        self.prepare_fixture()
        baseline = self.preview(); self.reference_path = baseline['assets'][0]['path']; self.saved = read_preview(baseline); spec = self.params['shape_preservation']
        self.items = []
        for i, (band, mesh) in enumerate(zip(spec.pop('protected_bands'), self.saved['result']['meshes'])):
            ref = dict(kind='preview', preview_id=baseline['transfer']['preview_id'], geometry_digest=digest(mesh['vertices']))
            self.items.append(dict(id='pin'+str(i), type='protection', selection=band, reference=ref, enforcement='exact', tolerance=1e-8))
            selection = dict(band, vertex_indices=list(range(len(mesh['vertices']))))
            self.items.append(dict(id='shape'+str(i), type='shape', selection=selection, weight=18., enforcement='soft', tolerance=1.))
        spec['constraints'] = dict(version='transfer_constraints.v1', items=self.items)

    def prepare_fixture(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root(); self.fixture = fixture(self.root, self.folder)
        self.params = copy.deepcopy(self.fixture['params'])
        sources = self.send('transfer_sources', source_objects=self.params['source_objects'])['transfer']['meshes']
        bands = [dict(source_object=r['object'], topology_digest=r['topology_digest'], geometry_digest=r['geometry_digest'], vertex_indices=[0, 1]) for r in sources]
        self.params['shape_preservation'] = dict(family_id='constraints', protected_bands=bands,
            obstacle_instance_ids=[self.fixture['owner']], tolerance=1e-4, validation_samples=64, settings=dict(max_iterations=4))

    def test_native_types_report_and_exact_snapshot(self):
        result = read_preview(self.preview())['result']; data = result['shape_preservation']
        self.assertEqual(result['method'], 'shared_cubic_rbf_local_constraints.v1')
        self.assertEqual(data['fitting']['method'], 'indexed_local_constraints.v1')
        pins = [r for r in data['constraints'] if r['type'] == 'protection']
        self.assertTrue(all(r['maximum_residual'] == 0 for r in pins))
        self.assertEqual(len(data['configuration']['items']), 4)

    def test_list_order_is_not_a_destructive_pipeline(self):
        a = read_preview(self.preview())['result']; self.items.reverse()
        b = read_preview(self.preview())['result']
        for left, right in zip(a['meshes'], b['meshes']): np.testing.assert_array_equal(left['vertices'], right['vertices'])

    def test_duplicate_id_stale_source_and_unknown_type_rejected(self):
        params = copy.deepcopy(self.params); items = params['shape_preservation']['constraints']['items']
        items.append(items[0]); self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'TRANSFER_CONSTRAINT_DUPLICATE_ID')
        params = copy.deepcopy(self.params); params['shape_preservation']['constraints']['items'][0]['selection']['geometry_digest'] = 'old'
        self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'STALE_TRANSFER_SOURCE')
        params = copy.deepcopy(self.params); params['shape_preservation']['constraints']['items'][0]['type'] = 'curvature'
        self.assertTrue(self.send('transfer_preview', **params)['diagnostics'][0]['code'].startswith('SCHEMA_'))

    def test_invalid_reference_rejected_on_preview_and_replay(self):
        payload = message(self.root, 'transfer_preview', **self.params); first = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertIn(first['status'], ('success', 'unresolved'))
        files = [Path(self.reference_path)]
        self.assertEqual(len(files), 1); value = json.loads(files[0].read_text())
        value['result']['meshes'][0]['vertices'][0][0] += 1.; files[0].write_text(json.dumps(value))
        result = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_TRANSFER_CONSTRAINT_REFERENCE')
        result = self.send('transfer_publish', preview_id=first['transfer']['preview_id'])
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_TRANSFER_CONSTRAINT_REFERENCE')

    def attachment(self):
        row = self.items[0]; target = copy.deepcopy(self.params['correspondences'][0]['target']); binding = target.pop('surface_binding')
        row.update(type='attachment', target=target, target_bindings=[binding]*2)
        row.pop('reference'); row['coverage'] = dict(intended=dict(vertex_indices=[0, 1, 2, 3]), axes=[[1, 0, 0], [0, 1, 0]], stations=[2, 2], minimum_fraction=.95)
        return row

    def test_incomplete_attachment_cannot_pass_with_exact_pins(self):
        row = self.attachment(); result = read_preview(self.preview())['result']
        report = next(r for r in result['shape_preservation']['constraints'] if r['id'] == row['id'])
        self.assertEqual(report['maximum_residual'], 0.); self.assertEqual(report['status'], 'unresolved')
        self.assertEqual(report['coverage']['vertex_fraction'], .5)
        self.assertIn('TRANSFER_CONSTRAINT_UNSATISFIED', [r['code'] for r in result['diagnostics']])

    def test_attachment_target_and_triangle_selection_validation(self):
        row = self.attachment(); row['selection'].pop('vertex_indices'); row['selection']['triangle_indices'] = [999999]
        self.assertEqual(self.send('transfer_preview', **self.params)['diagnostics'][0]['code'], 'TRANSFER_SHAPE_INDEX')
        row['selection'].pop('triangle_indices'); row['selection']['vertex_indices'] = [0, 1]; row['target']['topology_digest'] = 'old'
        self.assertEqual(self.send('transfer_preview', **self.params)['diagnostics'][0]['code'], 'TRANSFER_TARGET_TOPOLOGY_CHANGED')

    def test_explicit_guide_can_be_disabled_and_localized(self):
        row = copy.deepcopy(self.items[1]); row.update(id='guide', type='guide', weight=0., reference=dict(kind='initial_field'), falloff=.2)
        row['selection']['vertex_indices'] = [3]; self.items.append(row)
        result = read_preview(self.preview())['result']; report = next(r for r in result['shape_preservation']['constraints'] if r['id'] == 'guide')
        self.assertEqual(report['status'], 'disabled'); self.assertEqual(report['active_vertex_indices'], [])
        self.assertEqual(report['reference_status'], 'initial_skeletal_field_not_attachment_retargeted')

    def test_configuration_survives_publish_and_reload(self):
        preview = self.preview(); result = self.send('transfer_publish', preview_id=preview['transfer']['preview_id'])
        self.assertTrue(result['published'], result); root_name = self.root.name
        path = Path(self.folder)/'constrained.blend'; StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); self.root = bpy.data.objects[root_name]
        manifest = json.loads(bpy.data.collections[result['transfer']['collection']]['af_transfer_manifest'])
        self.assertEqual(manifest['shape_preservation']['configuration'], self.params['shape_preservation']['constraints'])
        for row in result['transfer']['objects']:
            obj = bpy.data.objects[row['name']]; self.assertFalse(obj.hide_get()); self.assertEqual(obj.display_type, 'TEXTURED')

    def test_clearance_conflict_reports_constraint_ids(self):
        row = self.attachment(); row['coverage']['intended']['vertex_indices'] = [0, 1]
        clearance = dict(id='gap_at_contact', type='clearance', selection=copy.deepcopy(row['selection']), weight=20.,
                         enforcement='soft', tolerance=1e-5, clearance=.2, obstacle_instance_ids=[self.fixture['owner']])
        self.items.append(clearance); result = self.send('transfer_preview', **self.params)
        self.assertEqual(result['diagnostics'][0]['code'], 'TRANSFER_CONSTRAINT_CONFLICT')
        self.assertIn('gap_at_contact', result['diagnostics'][0]['message']); self.assertIn(row['id'], result['diagnostics'][0]['message'])

    def test_triangle_domains_and_nonzero_local_guide(self):
        shape = self.items[1]; shape['selection'].pop('vertex_indices'); shape['selection']['triangle_indices'] = [0, 1]
        guide = dict(id='local_guide', type='guide', selection=copy.deepcopy(shape['selection']), weight=.3,
                     enforcement='soft', tolerance=2., reference=dict(kind='initial_field'), falloff=.02)
        self.items.append(guide); result = read_preview(self.preview())['result']
        report = next(r for r in result['shape_preservation']['constraints'] if r['id'] == 'local_guide')
        self.assertGreater(len(report['active_vertex_indices']), 0)
        self.assertLess(len(report['active_vertex_indices']), len(result['meshes'][0]['vertices']))

    def test_attachment_only_draft_change_blocks_replay_and_publish(self):
        row = self.attachment(); doc = copy.deepcopy(self.fixture['document']); doc['document_id'] = 'constraint_only'
        self.assertEqual(self.send('draft', document_id=doc['document_id'], expected_draft_revision=0, document=doc)['status'], 'success')
        row['target']['document_id'] = doc['document_id']; payload = message(self.root, 'transfer_preview', **self.params)
        first = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(self.send('draft', document_id=doc['document_id'], expected_draft_revision=1, document=doc)['status'], 'success')
        replay = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(replay['diagnostics'][0]['code'], 'STALE_DRAFT_REVISION')
        result = self.send('transfer_publish', preview_id=first['transfer']['preview_id'])
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_DRAFT_REVISION')
