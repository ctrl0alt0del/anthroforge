"""Actual Blender publication, persisted reference meshes and restored warnings."""
import json
import tempfile
from pathlib import Path
from dataclasses import replace
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from adapters.warm_update import output
from adapters.warm_update.current_output import current_skin_result, bound_skin_result
from adapters.mesh_issues import publish, session, ArtifactListener
from test_warm_update_integration import _skin_result, _topology_result


class IssueIntegrationTests(BlenderTestCase):
    def test_invalid_quality_publishes_and_retains_truthful_report(self):
        owner = root(); value = _skin_result(0)
        bad = replace(value, validation=replace(value.validation, valid=False, watertight=False))
        obj = output.replace_outputs(bpy.context.scene, owner, bad)[0]
        restored = current_skin_result(owner, bpy.context.scene)
        self.assertFalse(restored.validation.valid)
        self.assertFalse(restored.validation.watertight)
        self.assertIn('QUALITY_WATERTIGHT', {r.code for r in session.REPOSITORY.records.values()})
        self.assertTrue(obj.get('af_issues_json'))

    def test_structural_failure_retains_previous_mesh(self):
        owner = root(); value = _skin_result(0)
        obj = output.replace_outputs(bpy.context.scene, owner, value)[0]; old = obj.data
        with self.assertRaises(ValueError):
            output.replace_outputs(bpy.context.scene, owner, replace(value, vertices=value.vertices*np.nan))
        self.assertEqual(obj.data, old)

    def test_partial_keeps_bound_skin_through_save_reopen(self):
        owner = root(); scene = bpy.context.scene
        skin, topo = output.replace_outputs(scene, owner, _skin_result(0), _topology_result(0))
        expected = current_skin_result(owner, scene).vertices.copy()
        output.replace_outputs(scene, owner, _skin_result(.1))
        self.assertTrue(topo['af_topology_stale'])
        self.assertNotEqual(topo['af_bound_skin'], skin.data)
        self._reopen(owner, expected)

    def _reopen(self, owner, expected):
        from anthroforge.adapters.authoring.scene import StaticScene
        name = owner.name
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'issues.blend'
            StaticScene(owner, bpy.context.scene).save_debug_copy(path)
            bpy.ops.wm.open_mainfile(filepath=str(path))
            owner = bpy.data.objects[name]
            np.testing.assert_array_equal(bound_skin_result(owner, bpy.context.scene).vertices, expected)
            ArtifactListener().check_all(None)
            self.assertTrue(any(r.code == 'TOPOLOGY_STALE' for r in session.REPOSITORY.records.values()))
            self.assertTrue(any(v['status'] == 'UNSCANNED' for v in session.REPOSITORY.provider_states.values()))

    def test_legacy_saved_mesh_has_unknown_quality(self):
        owner = root(); obj = output.replace_outputs(bpy.context.scene, owner, _skin_result(0))[0]
        obj['af_skin_stats_json'] = '{}'
        self.assertIsNone(current_skin_result(owner, bpy.context.scene).validation)

    def test_revision_guard_rejects_old_epoch(self):
        from types import SimpleNamespace
        from adapters.job_revision import attach, require_current
        owner = root()
        with tempfile.TemporaryDirectory() as folder:
            job = SimpleNamespace(spec=SimpleNamespace(root_name=owner.name, cancel_path=folder+'/cancel'))
            attach(job, bpy.context.scene); require_current(job, bpy.context.scene)
            session.reset()
            with self.assertRaisesRegex(RuntimeError, 'source changed'):
                require_current(job, bpy.context.scene)
