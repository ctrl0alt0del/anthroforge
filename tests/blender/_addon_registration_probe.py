"""Normal restricted registration, deferred work, cancellation and file loading."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
import importlib.util
import sys
import unittest

import addon_utils
import bpy
from _bpy_restrict_state import RestrictBlend

ADDON_PATH = Path(__file__).resolve().parents[2]


def load_test_addon():
    path = ADDON_PATH / '__init__.py'
    spec = importlib.util.spec_from_file_location('anthroforge', path,
                                                  submodule_search_locations=[str(ADDON_PATH)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['anthroforge'] = module
    with RestrictBlend():
        spec.loader.exec_module(module)
    module.__time__ = path.stat().st_mtime
    module.__addon_enabled__ = False
    return module


ADDON = load_test_addon()
from anthroforge.core.vcp import shared_point_storage as storage
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.ui import warnings


def run_pending(callback):
    assert bpy.app.timers.is_registered(callback)
    bpy.app.timers.unregister(callback)
    assert callback() is None


def make_legacy_root():
    owner = bpy.data.objects.new('LegacyRoot', None)
    bpy.context.scene.collection.objects.link(owner)
    owner['anthroforge_root'] = True
    with suppress_vcp_prop_updates():
        fiber = owner.af_vcp_system.fibers.add(); fiber.id = 'LEGACY'
        for prefix, value in (('a_', 'origin'), ('b_', 'insertion')):
            fiber[prefix + 'parent_id'] = 'SCP_' + value
            fiber[prefix + 'attach_param'] = value
        middle = fiber.mid_touches.add()
        middle['parent_id'], middle['attach_param'] = 'SCP_route', 'route'
        middle['normal_offset'] = 0.125
    return owner


class RegistrationProbe(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.errors = []
        self.enable()

    def tearDown(self):
        if ADDON.__addon_enabled__:
            self.disable()

    def enable(self):
        module = addon_utils.enable('anthroforge', default_set=False, handle_error=self.errors.append)
        self.assertEqual(self.errors, [])
        self.assertIs(module, ADDON)
        self.assertEqual(Path(module.__file__).resolve().parent, ADDON_PATH)
        self.assertTrue(module.__addon_enabled__)

    def disable(self):
        addon_utils.disable('anthroforge', default_set=False, handle_error=self.errors.append)
        self.assertEqual(self.errors, [])
        self.assertFalse(ADDON._RUNTIME_REGISTERED)

    def assert_warning_panel(self):
        manager = bpy.context.window_manager
        self.assertIsInstance(manager.af_warnings_expanded, bool)
        manager.af_warnings_expanded = True
        layout = MagicMock()
        warnings.draw(layout, bpy.context)
        self.assertEqual(layout.box.return_value.prop.call_args.args[:2],
                         (manager, 'af_warnings_expanded'))
        layout.box.return_value.template_list.assert_called_once()

    def test_normal_registration_and_pending_disable(self):
        self.assertFalse(bpy.context.window_manager.af_warnings_expanded)
        self.assert_warning_panel()
        self.assertTrue(bpy.app.timers.is_registered(storage._migrate_when_ready))
        self.assertTrue(bpy.app.timers.is_registered(warnings._refresh_when_ready))
        self.disable()
        self.assertFalse(hasattr(bpy.context.window_manager, 'af_warnings_expanded'))
        self.assertFalse(bpy.app.timers.is_registered(storage._migrate_when_ready))
        self.assertFalse(bpy.app.timers.is_registered(warnings._refresh_when_ready))
        self.assertNotIn(storage.migrate_loaded, bpy.app.handlers.load_post)
        self.enable()
        ADDON.register()
        self.assertEqual(bpy.app.handlers.load_post.count(storage.migrate_loaded), 1)
        self.assert_warning_panel()

    def test_deferred_migration_projection_and_load_post(self):
        owner = make_legacy_root()
        self.assertEqual(len(owner.af_vcp_system.authored_points), 0)
        with RestrictBlend():
            self.assertGreater(storage._migrate_when_ready(), 0)
            self.assertGreater(warnings._refresh_when_ready(), 0)
        run_pending(storage._migrate_when_ready)
        run_pending(warnings._refresh_when_ready)
        self.assert_legacy_bindings(owner)
        self.assertEqual(len(bpy.context.window_manager.af_warning_rows), 0)
        self.assert_reload_migration(owner)

    def test_load_post_migrates_a_legacy_file(self):
        owner = make_legacy_root()
        name = owner.name
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / 'legacy.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path)
            self.assertEqual(len(owner.af_vcp_system.authored_points), 0)
            bpy.ops.wm.open_mainfile(filepath=path)
        self.assert_legacy_bindings(bpy.data.objects[name])
        self.assertFalse(bpy.app.timers.is_registered(storage._migrate_when_ready))

    def assert_legacy_bindings(self, owner):
        system = owner.af_vcp_system
        self.assertEqual(system.point_schema_version, 1)
        self.assertEqual(len(system.authored_points), 3)
        points = [storage.point_record(item, slot) for item, slot, _ in storage.slots(system.fibers[0])]
        self.assertEqual(len({point.id for point in points}), 3)
        self.assertEqual([(point.parent_id, point.attach_param) for point in points],
                         [('SCP_origin', 'origin'), ('SCP_route', 'route'), ('SCP_insertion', 'insertion')])
        self.assertEqual([point.normal_offset for point in points], [0, 0.125, 0])

    def assert_reload_migration(self, owner):
        name = owner.name
        identities = [point.id for point in owner.af_vcp_system.authored_points]
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / 'registration.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
        owner = bpy.data.objects[name]
        self.assert_legacy_bindings(owner)
        self.assertEqual([point.id for point in owner.af_vcp_system.authored_points], identities)
        self.assertTrue(hasattr(bpy.context.window_manager, 'af_warnings_expanded'))


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RegistrationProbe))
if not result.wasSuccessful():
    raise SystemExit(1)
print('REGISTRATION_PROBE_OK', ADDON.__file__)
