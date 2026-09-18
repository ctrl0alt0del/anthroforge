"""Standalone example regeneration without embedded scripts or lab imports."""
import bpy
from tempfile import TemporaryDirectory
from pathlib import Path
import numpy as np
from _helpers import BlenderTestCase
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


class BranchFixtureReloadTests(BlenderTestCase):
    def test_native_fixture_opens_and_regenerates(self):
        _roundtrip_fixture()
        root = next(o for o in bpy.data.objects if len(o.af_vcp_system.muscles))
        muscle = root.af_vcp_system.muscles[0]
        curves = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')]
        self.assertEqual(len(curves), 4)
        self.assertTrue(all(o.type == 'CURVE' and not o.hide_get() and not o.hide_viewport for o in curves))
        self.assertFalse(any('ENABLE' in text.name for text in bpy.data.texts))
        self._regenerate(root, muscle)

    def _regenerate(self, root, muscle):
        output = next(o for o in bpy.context.scene.objects if o.get('af_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL')
        before = np.array([v.co[:] for v in output.data.vertices])
        with suppress_vcp_prop_updates():
            muscle.inflation_max_value = .35
        register_muscle_sync().sync_root_to_scene(root, bpy.context.scene)
        after = np.array([v.co[:] for v in output.data.vertices])
        self.assertEqual(before.shape, after.shape)
        self.assertGreater(float(np.max(np.abs(before-after))), .01)
        self.assertTrue(np.isfinite(after).all())


def _roundtrip_fixture():
    from _branch_fixture import create_fixture
    from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync
    from anthroforge.adapters.authoring.scene import StaticScene
    root, muscle, connection, fibers = create_fixture()
    register_fiber_surface_sync().sync_root_to_scene(root, bpy.context.scene)
    register_muscle_sync().sync_root_to_scene(root, bpy.context.scene)
    with TemporaryDirectory() as directory:
        path = str(Path(directory)/'native_branch.blend')
        StaticScene(root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=path, use_scripts=False)
