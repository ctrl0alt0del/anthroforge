"""SCP mirror reuse keeps evaluated output, ownership, and lifecycle semantics."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, root, empty_object, mesh_object, scp_with_object
from test_mirror_index import CountingObjects
from anthroforge.core.scp_runtime import mirror_scene as mirrors
from anthroforge.core.scp_runtime.common import scp_prop_map
from anthroforge.core.scp_runtime.mirror_roles import apply_scp_mirror_roles
from anthroforge.core.visualization.sync import register_sync


def refresh(owner, targets=None):
    apply_scp_mirror_roles(owner)
    mirrors.sync_mirrors(register_sync(), owner, bpy.context.scene, scp_prop_map(owner), targets)
    return [o for o in bpy.context.scene.objects if o.get('af_scp_mirror') and o.get('af_root_name') == owner.name]


def fixture():
    owner = root()
    source = scp_with_object(owner, 'Source', empty_object('Source'), with_geometry=False)
    target = scp_with_object(owner, 'Target', mesh_object('Target', (2., 0., 0.)))
    target.parent_id, source.mirror_enabled = source.id, True
    return owner, source, target, refresh(owner)[0]


def points(obj):
    return [tuple(v.co) for v in obj.data.vertices]


class TrackedState:
    def __init__(self, **values):
        self.__dict__.update(values, writes=[])

    def __setattr__(self, key, value):
        self.writes.append(key)
        self.__dict__[key] = value


class SCPMirrorReuseTests(BlenderTestCase):
    def test_repeated_edits_reuse_object_without_mesh_accumulation(self):
        owner, _, target, mirror = fixture(); uid = mirror.session_uid
        counts = (len(bpy.data.objects), len(bpy.data.meshes))
        for offset in (.2, .4, .6):
            old_mesh = mirror.data.session_uid
            target.geometry_object_ref.data.vertices[0].co.z = offset
            target.geometry_object_ref.data.update(); mirror = refresh(owner)[0]
            self.assertEqual(mirror.session_uid, uid); self.assertNotEqual(mirror.data.session_uid, old_mesh)
            self.assertEqual(points(mirror), points(target.geometry_object_ref))
            self.assertEqual((len(bpy.data.objects), len(bpy.data.meshes)), counts)

    def test_source_modifier_is_baked_on_every_reuse(self):
        owner, _, target, mirror = fixture(); uid = mirror.session_uid
        source = target.geometry_object_ref; modifier = source.modifiers.new('Thickness', 'SOLIDIFY')
        for thickness in (.1, .3):
            modifier.thickness = thickness; mirror = refresh(owner)[0]
            evaluated = source.evaluated_get(bpy.context.view_layer.depsgraph)
            self.assertEqual(mirror.session_uid, uid); self.assertFalse(mirror.modifiers)
            self.assertEqual(points(mirror), points(evaluated))
            self.assertGreater(len(mirror.data.vertices), len(source.data.vertices))

    def test_legacy_modifiers_constraints_and_animation_force_baked_replacement(self):
        owner, _, _, mirror = fixture()
        alterations = (lambda o: o.modifiers.new('Old', 'SOLIDIFY'),
                       lambda o: o.constraints.new('LIMIT_LOCATION'), lambda o: o.animation_data_create())
        for alter in alterations:
            uid = mirror.session_uid; mirror['af_authoring_id'] = 'persistent'; alter(mirror)
            mirror = refresh(owner)[0]
            self.assertNotEqual(mirror.session_uid, uid); self.assertEqual(mirror['af_authoring_id'], 'persistent')
            self.assertFalse(mirror.modifiers); self.assertFalse(mirror.constraints)
            self.assertIsNone(mirror.animation_data)

    def test_single_legacy_empty_is_replaced_by_mesh(self):
        owner, _, target, mirror = fixture(); collection = mirror.users_collection[0]
        mirrors.remove_obj(mirror)
        legacy = bpy.data.objects.new('Legacy', None); collection.objects.link(legacy)
        for key, value in dict(af_root_name=owner.name, af_source_scp_id=target.id, af_scp_mirror=True).items():
            legacy[key] = value
        legacy['af_authoring_id'] = 'persistent'; uid = legacy.session_uid
        result = refresh(owner)
        self.assertEqual(len(result), 1); self.assertEqual(result[0].type, 'MESH')
        self.assertNotEqual(result[0].session_uid, uid); self.assertEqual(result[0]['af_authoring_id'], 'persistent')

    def test_failed_capture_removes_stale_output_and_next_pass_recovers(self):
        owner, _, target, mirror = fixture(); name = mirror.name
        with patch.object(mirrors, '_copy_eval_mesh', return_value=None):
            self.assertFalse(refresh(owner, {target.id}))
        self.assertNotIn(name, bpy.data.objects)
        self.assertEqual(len(refresh(owner, {target.id})), 1)

    def test_shared_previous_mesh_is_preserved_for_other_user(self):
        owner, _, _, mirror = fixture(); old = mirror.data; before = points(mirror)
        user = bpy.data.objects.new('OtherUser', old); bpy.context.scene.collection.objects.link(user)
        mirror = refresh(owner)[0]
        self.assertNotEqual(mirror.data, old); self.assertEqual(user.data, old)
        self.assertEqual(points(user), before); self.assertEqual(old.users, 1)

    def test_state_changes_propagate_without_redundant_writes(self):
        values = dict(color=(.2, .3, .4, 1.), display_type='SOLID', show_all_edges=False,
                      show_in_front=True, show_wire=False, hide_render=False)
        source = SimpleNamespace(**values); target = TrackedState(**values)
        mirrors.MirrorSceneSync._copy_object_state(None, source, target)
        self.assertEqual(target.writes, [])
        source.hide_render = True; source.color = (.4, .3, .2, 1.)
        mirrors.MirrorSceneSync._copy_object_state(None, source, target)
        self.assertEqual(target.writes, ['color', 'hide_render'])

    def test_reuse_preserves_isolation_and_external_references(self):
        owner, _, _, mirror = fixture(); mirror.hide_set(True)
        follower = empty_object('Follower'); constraint = follower.constraints.new('COPY_LOCATION')
        constraint.target = mirror; uid = mirror.session_uid
        result = refresh(owner)[0]
        self.assertEqual(result.session_uid, uid); self.assertTrue(result.hide_get())
        self.assertEqual(constraint.target, result)

    def test_run_scans_scene_once_for_lookup_and_cleanup(self):
        owner, _, _, _ = fixture(); scene = bpy.context.scene
        context = mirrors.MirrorSceneSync(register_sync(), owner, scene, scp_prop_map(owner))
        counted = CountingObjects(scene.objects); context.scene = SimpleNamespace(objects=counted)
        with patch.object(mirrors, 'update_scene_view_layer'), \
             patch.object(mirrors, 'depsgraph_for_scene', return_value=bpy.context.view_layer.depsgraph):
            context.run()
        self.assertEqual(counted.scans, 1)

    def test_reopened_file_builds_fresh_index_and_reuses_saved_object(self):
        owner, _, _, mirror = fixture(); name = owner.name; mirror['af_authoring_id'] = 'persistent'
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'scp-mirror.blend'); bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path); owner = bpy.data.objects[name]
            saved = next(o for o in bpy.context.scene.objects if o.get('af_scp_mirror'))
            uid = saved.session_uid; result = refresh(owner)[0]
            self.assertEqual(result.session_uid, uid); self.assertEqual(result['af_authoring_id'], 'persistent')
