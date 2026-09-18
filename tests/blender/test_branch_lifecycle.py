import bpy
import numpy as np
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.shared_point_storage import point_users
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.vcp_mirror_runtime import sync_vcp_mirrors


class BranchLifecycleTests(BlenderTestCase):
    def test_undo_redo_preserves_shared_identity(self):
        root, muscle, connection, fibers = create_fixture()
        name, key = root.name, fibers[0].mid_touches[0].point_id
        bpy.ops.ed.undo_push(message='Original branch')
        with suppress_vcp_prop_updates():
            fibers[0].mid_touches[0].normal_offset = .05
        bpy.ops.ed.undo_push(message='Shared offset')
        bpy.ops.ed.undo()
        self._assert_offset(name, key, 0.)
        bpy.ops.ed.redo()
        self._assert_offset(name, key, .05)

    def _assert_offset(self, name, key, offset):
        root = bpy.data.objects[name]
        point = next(p for p in root.af_vcp_system.authored_points if p.id == key)
        self.assertAlmostEqual(point.normal_offset, offset)
        self.assertEqual(len(point_users(root, key)), 2)

    def test_native_mirror_reflects_entire_assembled_mesh(self):
        root, muscle, connection, fibers = create_fixture()
        with suppress_vcp_prop_updates():
            root.af_scp_system.scps[0].mirror_enabled = True
            root.af_scp_system.scps[0].mirror_axis = 'X'
        register_muscle_sync().sync_root_to_scene(root, bpy.context.scene)
        sync_vcp_mirrors(root, bpy.context.scene, target_muscle_ids={muscle.id})
        source = next(o for o in bpy.context.scene.objects if o.get('af_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL')
        mirror = next(o for o in bpy.context.scene.objects if o.get('af_source_muscle_id') == muscle.id and o.get('af_muscle_surface') == 'INFL')
        a = np.array([source.matrix_world @ v.co for v in source.data.vertices])
        b = np.array([mirror.matrix_world @ v.co for v in mirror.data.vertices])
        np.testing.assert_allclose(b, a*[-1, 1, 1], atol=1e-6)
