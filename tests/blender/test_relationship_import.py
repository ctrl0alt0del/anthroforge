"""Real package import and rollback, including roots without Free fibers."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import bpy
from _helpers import BlenderTestCase
from _stacking_fixture import fixture
from test_muscle_stacking import refresh
from test_muscle_relationships import configure, first
from anthroforge.core.muscle_relationships import store, migration
from anthroforge.core.importing.service import import_package_from_blend
from anthroforge.core.importing.free_fibers import atomic_import


class RelationshipImport(BlenderTestCase):
    def test_package_import_remaps_into_existing_namespace(self):
        root, _, _ = fixture(); state = configure(root, refresh(root), excluded=True)
        before = store.read(root); prior_ids = set(before['records']); namespace = before['namespace']
        root.af_pair_settings.search = .123
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'source.blend'); bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
            result = import_package_from_blend(path, bpy.context)
            self.assertEqual(result.muscle_count, 2)
        document = store.read(root); self.assertEqual(document['namespace'], namespace)
        self.assertTrue(prior_ids <= set(document['records'])); self.assertAlmostEqual(root.af_pair_settings.search, .123)
        imported = [r for k, r in document['records'].items() if k not in prior_ids]
        self.assertEqual(len(imported), 1); self.assertTrue(imported[0]['intent']['excluded'])
        self.assertFalse(set(map(tuple, first(state)['pair'])) & set(map(tuple, imported[0]['pair'])))

    def test_non_free_import_failure_restores_relationship_data(self):
        root, _, _ = fixture(); refresh(root); before = root[store.KEY]
        snapshot = SimpleNamespace(fibers=[], branching={}, relationships=store.read(root))
        def fail():
            root[store.KEY] = '{}'
            raise ValueError('import failed')
        with self.assertRaises(ValueError): atomic_import(root, bpy.context.scene, snapshot, (), fail)
        self.assertEqual(root[store.KEY], before)

    def test_append_gets_new_namespace_and_preserves_intent(self):
        root, _, _ = fixture(); configure(root, refresh(root), excluded=True); name = root.name; original = store.read(root)
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'append.blend'); bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
            with bpy.data.libraries.load(path, link=False) as (_, target): target.objects = [name]
            copy = target.objects[0]
            self.assertNotEqual(store.read(copy)['namespace'], original['namespace'])
            self.assertTrue(next(iter(store.read(copy)['records'].values()))['intent']['excluded'])

    def test_experimental_migration_is_explicit(self):
        root, _, _ = fixture(); refresh(root); document = store.read(root)
        root['af_experiment_relationships_v1'] = store.encode(document); root.pop(store.KEY); root.pop(store.NAMESPACE)
        empty = migration.ensure(root); self.assertFalse(empty['records'])
        result = migration.explicit_experiment(root)
        self.assertEqual(len(result['records']), len(document['records']))
