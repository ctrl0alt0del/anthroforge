"""Regression: deformation may change quad tessellation without changing bindings."""
import json
import bpy
from _helpers import BlenderTestCase, select_only, root
from test_soft_tissue_muscle_attachment import _muscle_tissue, _binding_payloads, _tissue_proxy, _world_points
from anthroforge.core.vcp.attachment_backend import surface_binding_topology
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.runtime_state import soft_tissue_status, soft_tissue_diagnostic
from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync
from anthroforge.core.visualization.sync_runner import clear_pending_runtime
from anthroforge.app.queries.soft_tissue_target import target_choices, picker_label, creation_uses_fibers
from anthroforge.core.vcp.surface_reference import from_object, key
from test_soft_tissue_workflows import _create_surface_tissue


def _quad(obj, bent=False, faces=((0, 1, 2, 3),)):
    mesh = bpy.data.meshes.new('Tessellation regression')
    second = (-.2, .2, 1.) if bent else (1., -1., 0.)
    mesh.from_pydata([(-1., -1., 0.), second, (1., 1., 0.), (-1., 1., 0.)], (), faces)
    old, obj.data = obj.data, mesh
    if not old.users: bpy.data.meshes.remove(old)
    bpy.context.view_layer.update(); clear_pending_runtime()


def _sync(owner, tissue, recapture=False):
    scope = {tissue.id: 'ALL'} if recapture else None
    register_soft_tissue_sync().sync_root_to_scene(owner, bpy.context.scene, {tissue.id}, scope, force=True)
    clear_pending_runtime()


def _fixture(legacy=False):
    owner, muscle, tissue, _base, obj = _muscle_tissue('INFL')
    with suppress_vcp_prop_updates(): tissue.relaxation_mode = 'NONE'
    _quad(obj); _sync(owner, tissue, True)
    if legacy: _legacy_metadata(tissue, surface_binding_topology(obj))
    return owner, muscle, tissue, obj


def _legacy_metadata(tissue, topology):
    with suppress_vcp_prop_updates():
        tissue.attachment_topology_signature = topology
        for obj, attr in _payload_fields(tissue):
            value = json.loads(getattr(obj, attr)); value['topology_signature'] = topology
            setattr(obj, attr, json.dumps(value))


def _payload_fields(tissue):
    return [(tissue, 'control_bindings_json'), (tissue, 'base_bindings_json')] + [(a, 'bindings_json') for a in tissue.attachments]


def _retained_rows(tissue):
    return [json.loads(getattr(obj, attr))['bindings'] for obj, attr in _payload_fields(tissue)]


def _remove_inner_seals(tissue):
    with suppress_vcp_prop_updates():
        for obj, attr in _payload_fields(tissue):
            value = json.loads(getattr(obj, attr))
            for row in value['bindings']:
                binding = json.loads(row['raw'])
                binding.pop('target', None); binding.pop('topology_signature', None)
                row['raw'] = json.dumps(binding)
            setattr(obj, attr, json.dumps(value))


def _legacy_scp_fixture():
    host, _scp, _base, tissue = _create_surface_tissue()
    _quad(host); _sync(root(), tissue, True)
    _legacy_metadata(tissue, surface_binding_topology(host)); _remove_inner_seals(tissue)
    return host, tissue


class SoftTissueTopologyTests(BlenderTestCase):
    def test_new_bindings_follow_changed_tessellation_without_recapture(self):
        owner, _muscle, tissue, obj = _fixture()
        before, payloads = _world_points(_tissue_proxy(tissue.id)), _binding_payloads(tissue)
        original = surface_binding_topology(obj)
        _quad(obj, True); self.assertNotEqual(original, surface_binding_topology(obj))
        _sync(owner, tissue)
        self.assertEqual(soft_tissue_status(tissue), 'CLEAN', soft_tissue_diagnostic(tissue))
        self.assertNotEqual(before, _world_points(_tissue_proxy(tissue.id)))
        self.assertEqual(payloads, _binding_payloads(tissue))
        _quad(obj); _sync(owner, tissue)
        self.assertEqual(before, _world_points(_tissue_proxy(tissue.id)))

    def test_legacy_envelopes_recover_after_tessellation_already_changed(self):
        owner, _muscle, tissue, obj = _fixture(True)
        rows = _retained_rows(tissue)
        _quad(obj, True); _sync(owner, tissue)
        self.assertEqual(soft_tissue_status(tissue), 'CLEAN', soft_tissue_diagnostic(tissue))
        self.assertEqual(rows, _retained_rows(tissue))
        self.assertTrue(tissue.attachment_topology_signature.startswith('connectivity-v1:'))
        self.assertTrue(all(json.loads(getattr(o, a))['topology_signature'] == tissue.attachment_topology_signature
                            for o, a in _payload_fields(tissue)))

    def test_actual_connectivity_change_with_same_vertex_count_is_rejected(self):
        owner, _muscle, tissue, obj = _fixture(True)
        before, payloads = _world_points(_tissue_proxy(tissue.id)), _binding_payloads(tissue)
        _quad(obj, faces=((0, 1, 2), (0, 2, 3))); _sync(owner, tissue)
        self.assertEqual(soft_tissue_status(tissue), 'ERROR')
        self.assertEqual((before, payloads), (_world_points(_tissue_proxy(tissue.id)), _binding_payloads(tissue)))
        self.assertEqual(_tissue_proxy(tissue.id)['af_soft_tissue_output_state'], 'STALE')
        _quad(obj); _sync(owner, tissue)
        self.assertEqual(soft_tissue_status(tissue), 'CLEAN')
        self.assertNotIn('af_attachment_error', _tissue_proxy(tissue.id))

    def test_unsealed_legacy_scp_promotes_only_after_matching_old_topology(self):
        host, tissue = _legacy_scp_fixture()
        rows = _retained_rows(tissue)
        _sync(root(), tissue)
        self.assertEqual(soft_tissue_status(tissue), 'CLEAN', soft_tissue_diagnostic(tissue))
        _quad(host, True); _sync(root(), tissue)
        self.assertEqual(soft_tissue_status(tissue), 'CLEAN', soft_tissue_diagnostic(tissue))
        self.assertEqual(rows, _retained_rows(tissue))

    def test_unsealed_legacy_scp_cannot_guess_missing_connectivity(self):
        host, tissue = _legacy_scp_fixture()
        previous = _binding_payloads(tissue)
        _quad(host, True); _sync(root(), tissue)
        self.assertEqual(soft_tissue_status(tissue), 'ERROR')
        self.assertEqual(previous, _binding_payloads(tissue))

    def test_wrong_target_identity_cannot_use_legacy_compatibility(self):
        owner, _muscle, tissue, obj = _fixture(True)
        with suppress_vcp_prop_updates():
            value = json.loads(tissue.control_bindings_json); value['target']['id'] = 'MISSING'
            tissue.control_bindings_json = json.dumps(value)
        previous = _binding_payloads(tissue)
        _quad(obj, True); _sync(owner, tissue)
        self.assertEqual(soft_tissue_status(tissue), 'ERROR')
        self.assertIn('identity', soft_tissue_diagnostic(tissue)[3])
        self.assertEqual(previous, _binding_payloads(tissue))

    def test_picker_uses_named_roles_and_persistent_identity_after_rename(self):
        owner, muscle, _tissue, obj = _fixture()
        muscle.name = 'Pectoralis'; obj.name = 'Unrelated proxy name'
        rows = target_choices(owner, bpy.context.scene)
        self.assertEqual(rows[0][1], 'Pectoralis / Inflated surface')
        self.assertIn('Pectoralis / Base surface', [row[1] for row in rows])
        self.assertEqual(bpy.ops.af.pick_soft_tissue_target(surface_choice=key(from_object(obj))), {'FINISHED'})
        self.assertEqual(bpy.context.scene.af_new_soft_tissue_target_obj, obj)
        self.assertEqual(picker_label(bpy.context), 'Pectoralis / Inflated surface')
        self.assertEqual(bpy.ops.af.pick_soft_tissue_target(surface_choice='NONE'), {'FINISHED'})
        self.assertIsNone(bpy.context.scene.af_new_soft_tissue_target_obj)

    def test_fiber_source_does_not_offer_an_unused_target(self):
        owner, _muscle, _tissue, _obj = _fixture()
        source = next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy'))
        select_only(source)
        self.assertTrue(creation_uses_fibers(bpy.context))
