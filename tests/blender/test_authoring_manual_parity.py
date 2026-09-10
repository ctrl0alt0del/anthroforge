"""Authored attachments remain editable through the manual native fiber flow."""
import os
import tempfile
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from test_authoring_v04 import setup, call
from test_authoring_mirrors import publish
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring import lowering, native_resolver
from anthroforge.core.authoring.errors import AuthoringError
from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement_group, drain_fiber_refinements, fiber_refinement_group_state


class ManualParityTests(BlenderTestCase):
    def test_published_fibers_refine_with_native_owner_ids(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            publish(self, r, folder, value)
            ids = [f.id for f in r.af_vcp_system.fibers]
            with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
                token = request_fiber_refinement_group(r, bpy.context.scene, ids)
                self.assertTrue(drain_fiber_refinements())
            state = fiber_refinement_group_state(token)
            self.assertEqual(state['failures'], {}, state)
            self.assertEqual(set(state['committed']), set(ids), state)

    def test_nearest_route_guess_matches_manual_picker(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            scene = StaticScene(r, bpy.context.scene)
            resolver, name = resolver_for(value, scene)
            anchor = resolver.direct_anchor(name, [.9, .5, .5], 0)
            np.testing.assert_allclose(anchor.surface, [.5, 0, 2], atol=1e-6)
            expected = scene.snap_binding(anchor.owner, [.4, 0, 2])
            self.assertEqual(anchor.surface_binding, (tuple(expected['tri_vidx']), tuple(expected['tri_weights'])))
            shifted = resolver.direct_anchor(name, [.9, .5, .5], .03)
            np.testing.assert_allclose(shifted.point, [.53, 0, 2], atol=1e-6)

    def test_nearest_route_guess_cannot_escape_region(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            resolver, name = resolver_for(value, StaticScene(r, bpy.context.scene))
            resolver.domains[name]['polygons'] = [[[0, 0, 0], [0, 1, 0], [0, 0, 1]]]
            with self.assertRaises(AuthoringError) as raised:
                resolver.direct_anchor(name, [.9, .5, .5], 0)
            self.assertEqual(raised.exception.code, 'SAMPLE_OUTSIDE_ALLOWED_REGION')


def resolver_for(value, scene):
    inventory = scene.capture_authoring()
    ir = lowering.compile_document(value, inventory)
    resolver = native_resolver.DomainResolver(ir, value, scene.capture(inventory['scene_id']), inventory, scene.snap_binding)
    name = lowering.identity('/skeleton_profiles/default/regions/origin')
    return resolver, name
