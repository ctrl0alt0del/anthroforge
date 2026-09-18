"""Compare normal native publication and explicit debug exports across save/load."""
import tempfile
from pathlib import Path
import bpy
from _helpers import BlenderTestCase, root
from test_authoring_mirrors import mirrored_document, publish
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.presentation import prepare_debug_presentation
from anthroforge.core.visualization.category_visibility import category_objects


class AuthoringPresentationTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.root = root()
        publish(self, self.root, self.folder.name, mirrored_document(self.root, self.folder.name))

    def test_publication_uses_visible_native_source_and_mirror_curves(self):
        objects = curves(self.root)
        self.assertEqual(len(objects), 2 * len(self.root.af_vcp_system.fibers))
        for obj in objects:
            self.assertTrue(obj.visible_get(), obj.name)
            self.assertEqual(obj.display_type, 'TEXTURED')
            self.assertFalse(obj.hide_render)
            self.assertGreater(obj.data.bevel_depth, 0)

    def test_debug_export_restores_visibility_colors_and_persists(self):
        for space in views(): space.shading.type = 'MATERIAL'
        for obj in curves(self.root):
            obj.hide_set(True); obj.hide_viewport = True; obj.hide_render = True; obj.display_type = 'WIRE'
        for scp in self.root.af_scp_system.scps:
            scp.geometry_object_ref.color = (.5, .5, .5, 1)
        path = Path(self.folder.name) / 'debug.blend'
        StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True)
        self.root = bpy.data.objects['AF_ROOT']
        self.test_publication_uses_visible_native_source_and_mirror_curves()
        for scp in self.root.af_scp_system.scps:
            self.assertEqual(tuple(scp.geometry_object_ref.color), tuple(scp.color))
        self.assertTrue(all(s.shading.type == 'SOLID' and s.shading.color_type == 'OBJECT' for s in views()))

    def test_excluded_collection_and_second_view_layer_are_restored(self):
        scene = bpy.context.scene; other = scene.view_layers.new('Debug second')
        unrelated = bpy.data.objects.new('Unrelated', None); scene.collection.objects.link(unrelated)
        unrelated.hide_set(True)
        for layer in scene.view_layers:
            for obj in curves(self.root): obj.hide_set(True, view_layer=layer)
            layer.layer_collection.children['AF_VCP_VIS'].exclude = True
        prepare_debug_presentation(self.root, scene)
        for layer in scene.view_layers:
            self.assertTrue(all(o.visible_get(view_layer=layer) for o in curves(self.root)))
        self.assertTrue(unrelated.hide_get())

    def test_ordinary_checkpoint_copy_preserves_user_hiding(self):
        obj = curves(self.root)[0]; name = obj.name; obj.hide_set(True)
        path = Path(self.folder.name) / 'ordinary.blend'
        StaticScene(self.root, bpy.context.scene).save_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path))
        self.assertTrue(bpy.data.objects[name].hide_get())


def curves(root_obj):
    return tuple(o for o in category_objects(bpy.context.scene, root_obj, 'FIBER') if o.get('af_fiber_proxy'))


def views():
    return tuple(p for s in bpy.data.screens for a in s.areas for p in a.spaces if p.type == 'VIEW_3D')
