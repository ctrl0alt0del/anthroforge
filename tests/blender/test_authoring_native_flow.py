"""Published geometry remains controlled by fibers, even with obsolete metadata."""
import tempfile
from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase, root
from test_authoring_v03 import document, request
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.native_scene import BlenderScene
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
from anthroforge.core.authoring.regions import RegionResolver
from anthroforge.core.vcp import attachment_backend


class NativeFlowTests(BlenderTestCase):
    def test_fiber_endpoint_controls_surface_without_scp_lookup(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            result = execute(request(r, 'build', document=document(r), transaction='document_atomic'), r, bpy.context.scene, directory)
            self.assertTrue(result['published'], result)
            self.assertNotIn('af_authoring_material', r.af_vcp_system.fiber_surfaces[0])
            self.assertNotIn('af_authoring_material', r.af_vcp_system.muscles[0])
            verify_endpoint(self, r)


def verify_endpoint(test, r):
    fiber = r.af_vcp_system.fibers[0]
    points = persisted_fiber_points(bpy.context.scene, r.name, fiber.id)
    points[0] += Vector((.05, 0, 0))
    r.af_vcp_system.fiber_surfaces[0]['af_authoring_material'] = 'obsolete malformed payload'
    r.af_vcp_system.muscles[0]['af_authoring_material'] = 'obsolete malformed payload'
    register_fiber_sync().apply_points(r, bpy.context.scene, fiber, points, commit=True)
    with patch.object(RegionResolver, '__init__', side_effect=AssertionError('Read regions')):
        with patch.object(attachment_backend, 'attachment_runtime', side_effect=AssertionError('Surface resolved SCP attachments')):
            BlenderScene(r, bpy.context.scene).refresh()
    surface = next(o for o in bpy.context.scene.objects if o.get('af_fiber_surface_proxy'))
    base = next(o for o in bpy.context.scene.objects if o.get('af_muscle_surface') == 'BASE')
    for obj in (surface, base):
        np.testing.assert_allclose(obj.matrix_world @ obj.data.vertices[0].co, points[0], atol=1e-6)
