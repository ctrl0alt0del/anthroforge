"""Storage settings preserve normal Blender debug exports and user preferences."""
import json
from pathlib import Path
import bpy
from test_authoring_presentation import AuthoringPresentationTests
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.storage_export import export_preferences


class StorageExportTests(AuthoringPresentationTests):
    def setUp(self):
        super().setUp()
        value = dict(schema_version=1, immutable_asset_pool='pool', compress_journals=True,
                     export_save_versions=0, compress_blend_exports=True)
        (Path(self.folder.name) / '.authoring-storage.json').write_text(json.dumps(value))

    def test_backup_preference_restored_and_export_compressed(self):
        preferences = bpy.context.preferences.filepaths
        previous = preferences.save_version
        try:
            preferences.save_version = 3
            path = Path(self.folder.name) / 'policy.blend'
            for _ in range(2): StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
            self.assertEqual(preferences.save_version, 3)
            self.assertFalse(path.with_suffix('.blend1').exists())
            with path.open('rb') as stream: self.assertEqual(stream.read(4), bytes.fromhex('28b52ffd'))
        finally:
            preferences.save_version = previous

    def test_exception_restores_preference(self):
        previous = bpy.context.preferences.filepaths.save_version
        with self.assertRaisesRegex(RuntimeError, 'test'):
            with export_preferences(Path(self.folder.name) / 'failure.blend'):
                self.assertEqual(bpy.context.preferences.filepaths.save_version, 0)
                raise RuntimeError('test')
        self.assertEqual(bpy.context.preferences.filepaths.save_version, previous)
