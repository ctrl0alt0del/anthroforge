"""Native identity, legacy migration and save/reload without a fiber solve."""
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy
from _helpers import BlenderTestCase, root
from anthroforge.core.vcp import shared_point_storage as storage
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def make_fiber(system, key):
    fiber = system.fibers.add()
    fiber.id = key
    fiber.a_parent_id = 'CUBE'
    fiber.a_attach_param = 'indexed-origin'
    fiber.b_parent_id = 'CUBE'
    fiber.b_attach_param = 'indexed-end'
    return fiber


class SharedPointStorageTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root = root()
        self.system = self.root.af_vcp_system

    def test_shared_accessors_use_one_binding(self):
        with suppress_vcp_prop_updates():
            main = make_fiber(self.system, 'MAIN')
            branch = make_fiber(self.system, 'BRANCH')
            mid = main.mid_touches.add()
            mid.parent_id, mid.attach_param, mid.normal_offset = 'CUBE', 'junction', .06
            branch.a_point_id = mid.point_id
            branch.a_attach_param = 'edited'
        self.assertEqual(mid.attach_param, 'edited')
        self.assertAlmostEqual(storage.point_record(branch, 'a_point_id').normal_offset, .06)
        self.assertEqual([(f.id, i, r) for f, i, r in storage.point_users(self.root, mid.point_id)],
                         [('MAIN', 1, 'MID'), ('BRANCH', 0, 'START')])

    def test_migration_is_idempotent_and_keeps_coincident_occurrences_separate(self):
        with suppress_vcp_prop_updates():
            fiber = self.system.fibers.add(); fiber.id = 'LEGACY'
            raw = fiber.id_properties_ensure()
            for prefix in ('a_', 'b_'):
                raw[prefix+'parent_id'], raw[prefix+'attach_param'] = 'CUBE', 'same'
        with patch('anthroforge.app.runtime_api.schedule_context', side_effect=AssertionError('solve')):
            storage.migrate_root(self.root)
            keys = [p.id for p in self.system.authored_points]
            storage.migrate_root(self.root)
        self.assertEqual(keys, [p.id for p in self.system.authored_points])
        self.assertNotEqual(fiber.a_point_id, fiber.b_point_id)
        self.assertEqual(fiber.a_attach_param, 'same')
        self.assertEqual(fiber.b_attach_param, 'same')

    def test_compatibility_write_notifies_all_incident_fibers_once(self):
        with suppress_vcp_prop_updates():
            first, second = make_fiber(self.system, 'A'), make_fiber(self.system, 'B')
            second.a_point_id = first.a_point_id
        with patch('anthroforge.app.runtime_api.schedule_context') as schedule:
            first.a_attach_param = 'new'
        self.assertEqual(schedule.call_count, 1)
        self.assertEqual(second.a_attach_param, 'new')

    def test_save_reload_keeps_shared_identity(self):
        with suppress_vcp_prop_updates():
            first, second = make_fiber(self.system, 'A'), make_fiber(self.system, 'B')
            second.a_point_id = first.a_point_id
        name, key = self.root.name, first.a_point_id
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'shared.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
        fibers = bpy.data.objects[name].af_vcp_system.fibers
        self.assertEqual(fibers[0].a_point_id, key)
        self.assertEqual(fibers[1].a_point_id, key)
        self.assertEqual(fibers[1].a_attach_param, 'indexed-origin')
