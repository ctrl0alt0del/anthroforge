"""Evaluated IDs retain name-based collection membership during fiber callbacks."""
from types import SimpleNamespace as NS
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, root, empty_object
from test_mirror_index import CountingObjects
from anthroforge.core.visualization import fiber_sync_runtime as runtime
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import mark_endpoint_handle
from anthroforge.core.scp_runtime.common import mark_applied_matrix
from mathutils import Matrix


class FiberCallbackIndexTests(BlenderTestCase):
    def test_evaluated_object_matches_original_name_lookup(self):
        owner = root(); obj = empty_object('Control'); obj['af_root_name'] = owner.name
        bpy.context.view_layer.update(); evaluated = obj.evaluated_get(bpy.context.view_layer.depsgraph)
        collection = bpy.context.scene.collection; names = {o.name for o in collection.objects}
        self.assertNotEqual(evaluated.as_pointer(), obj.as_pointer())
        expected = runtime._is_relevant_update_obj(None, owner, collection, evaluated)
        self.assertTrue(expected)
        self.assertEqual(runtime._is_relevant_update_obj(None, owner, collection, evaluated, names), expected)

    def test_callback_scans_collection_once_and_does_not_use_get(self):
        owner = root(); obj = empty_object('Control'); obj['af_root_name'] = owner.name
        counted = CountingObjects(bpy.context.scene.collection.objects)
        graph = NS(updates=[NS(id=obj) for _ in range(100)])
        runtime._depsgraph_changed_fibers(register_fiber_sync(), owner, NS(objects=counted), graph)
        self.assertEqual(counted.scans, 1)

    def test_repeated_control_update_enqueues_once_through_indexed_path(self):
        owner = root(); handle = mark_endpoint_handle(empty_object('Control'), owner, 'F1', 'A')
        mark_applied_matrix(handle); handle.matrix_world = Matrix.Translation((.25, 0., 0.))
        graph = NS(updates=[NS(id=handle), NS(id=handle)])
        with patch.object(runtime, 'enqueue_control_intent', return_value=True) as enqueue:
            changed = runtime._depsgraph_changed_fibers(register_fiber_sync(), owner, bpy.context.scene.collection, graph)
        self.assertEqual(changed, {'F1'}); self.assertEqual(enqueue.call_count, 1)

    def test_rename_and_unlink_take_effect_on_next_callback(self):
        owner = root(); obj = empty_object('Control'); obj['af_root_name'] = owner.name
        collection = bpy.context.scene.collection; graph = NS(updates=[NS(id=obj)])
        with patch.object(runtime, 'classify_control_object', return_value=None) as classify, \
             patch.object(runtime, 'is_runtime_applied_matrix', return_value=False):
            runtime._depsgraph_changed_fibers(None, owner, collection, graph)
            obj.name = 'Renamed'; runtime._depsgraph_changed_fibers(None, owner, collection, graph)
            collection.objects.unlink(obj); runtime._depsgraph_changed_fibers(None, owner, collection, graph)
        self.assertEqual(classify.call_count, 2)

    def test_foreign_roots_and_mesh_ids_are_rejected(self):
        owner = root(); foreign = empty_object('Foreign'); foreign['af_root_name'] = 'AnotherRoot'
        collection = bpy.context.scene.collection; names = {o.name for o in collection.objects}
        self.assertFalse(runtime._is_relevant_update_obj(None, owner, collection, foreign, names))
        mesh = bpy.data.meshes.new('Foreign')
        self.assertFalse(runtime._is_relevant_update_obj(None, owner, collection, mesh, names))
