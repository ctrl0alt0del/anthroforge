from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.importing.vcp import apply_vcp_snapshot
from anthroforge.core.vcp.shared_point_storage import point_users


class BranchImportTests(BlenderTestCase):
    def test_same_root_import_clones_identity_preserving_internal_sharing(self):
        root, muscle, connection, fibers = create_fixture()
        original = fibers[0].mid_touches[0].point_id
        snapshot = root_snapshot(root)
        with patch('anthroforge.core.importing.vcp._schedule_imported_sync'):
            result = apply_vcp_snapshot(snapshot, root, bpy.context)
        self.assertEqual(result.fiber_count, 4)
        surfaces = [s for s in root.af_vcp_system.fiber_surfaces if s.construction_mode == 'BRANCHED_LOFT']
        self.assertEqual(len(surfaces), 2)
        imported = surfaces[-1].branches[0].roots[0].point_id
        self.assertNotEqual(original, imported)
        self.assertEqual(len(point_users(root, original)), 2)
        self.assertEqual(len(point_users(root, imported)), 2)
