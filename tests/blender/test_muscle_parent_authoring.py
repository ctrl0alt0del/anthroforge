"""Typed API inputs and graph duplication without recapturing existing bindings."""
import os
import tempfile
from uuid import uuid4
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from test_muscle_parent_fibers import parent_fixture, arched_fiber, tissue_chain
from test_free_authoring import request
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.inventory import capture
from anthroforge.core.vcp.surface_reference import reference


class MuscleParentAuthoringTests(BlenderTestCase):
    def test_subtree_copy_preserves_branched_parent_surface_graph(self):
        import numpy as np
        from test_free_dispatch import branch_scene, flush
        from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request
        from anthroforge.core.vcp.branched_numeric import evaluate
        owner, muscle, _fibers = branch_scene(); original = muscle.id
        before = evaluate(_branched_request(owner, bpy.context.scene, muscle), 'NATIVE')
        self.assertEqual(bpy.ops.af.copy_scp_in_tree(scp_id=owner.af_scp_system.scps[0].id), {'FINISHED'}); flush()
        copied = owner.af_vcp_system.muscles[-1]; self.assertNotEqual(copied.id, original)
        after = evaluate(_branched_request(owner, bpy.context.scene, copied), 'NATIVE')
        self.assertFalse(after.error, after.error)
        np.testing.assert_allclose(before.base_vertices, after.base_vertices, atol=1e-6)
        np.testing.assert_allclose(before.inflated_vertices, after.inflated_vertices, atol=1e-6)

    def test_surface_chooser_keeps_fiber_active_and_lists_mirror_roles(self):
        from _helpers import select_only, find_flagged
        from test_muscle_parent_fibers import mirrored_surface
        from anthroforge.app.queries.fiber_attachment import surface_choices
        from anthroforge.core.vcp.surface_reference import key, from_object
        from anthroforge.ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
        owner, muscle, surface, parent = parent_fixture(); fiber, _points = arched_fiber(owner, surface, parent)
        mirror = mirrored_surface(owner, muscle, surface); target = key(from_object(mirror))
        items = surface_choices(owner, bpy.context.scene)
        self.assertTrue(any(row[0] == target and '/ INFL / mirror' in row[1] for row in items))
        self.assertTrue(any('/ BASE / source' in row[1] for row in items))
        select_only(find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id')); self.assertTrue(AF_PT_FiberEditPanel.poll(bpy.context))
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            self.assertEqual(bpy.ops.af.fiber_attachment(action='ADD', fiber_id=fiber.id, use_choice=True, surface_choice=target), {'FINISHED'})
        self.assertTrue(AF_PT_FiberEditPanel.poll(bpy.context)); self.assertIn(target, [s.target_id for s in fiber.attachment_supports])

    def test_typed_controlled_api_captures_positions_and_native_bindings(self):
        from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements
        owner, muscle, surface, parent = parent_fixture(); _fiber, points = arched_fiber(owner, surface, parent)
        targets = [dict(point_id=str(uuid4()), target=dict(type='MUSCLE', id=muscle.id), position=list(p)) for p in (points[0], points[-1])]
        value = request(owner, 'fibers.create_controlled', expected_scene_revision=capture(owner, bpy.context.scene)['revision'],
                        attachments=targets, settings=dict(node_count=8))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            result = execute(value, owner, bpy.context.scene, folder)
            self.assertEqual(result['status'], 'success', result); drain_fiber_refinements()
        created = owner.af_vcp_system.fibers[-1]
        self.assertEqual(reference(created.a_parent_id).entity_id, muscle.id)
        self.assertTrue(created.node_attachments_json)

    def test_subtree_copy_remaps_nested_muscle_fibers(self):
        from anthroforge.core.scp_runtime.object_roles import create_scp
        from anthroforge.core.scp_runtime.prop_update_guard import set_parent_id_raw
        from anthroforge.core.scp_runtime.copy import copy_scp_subtree
        owner, muscle, tissue, _surface = tissue_chain('LAYER')
        ids = [s.id for s in owner.af_scp_system.scps]; parent = create_scp(owner, 'Attachment test assembly')
        for scp in owner.af_scp_system.scps:
            if scp.id in ids: set_parent_id_raw(scp, parent.id)
        originals = {f.id: f.node_attachments_json for f in owner.af_vcp_system.fibers}
        copied = copy_scp_subtree(owner, bpy.context.scene, parent.id, child_ids=set(ids))
        self.assertTrue(copied)
        children = [f for f in owner.af_vcp_system.fibers if f.behavior_mode == 'FREE' and f.id not in originals]
        self.assertEqual(len(children), 2)
        self.assertTrue(all(reference(f.a_parent_id).entity_id != muscle.id for f in children))
        self.assertEqual(originals, {f.id: f.node_attachments_json for f in owner.af_vcp_system.fibers if f.id in originals})
