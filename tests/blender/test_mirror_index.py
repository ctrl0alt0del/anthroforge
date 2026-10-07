"""Mirror lookup cost, duplicate selection, and pass-local object lifetimes."""
from types import SimpleNamespace
import bpy
from _helpers import BlenderTestCase, root, mesh_object
from anthroforge.core.visualization import vcp_mirror_runtime as mirrors
from anthroforge.core.visualization.mirror_objects import _remove_orphan_data, remove_obj
from anthroforge.core.visualization.vcp_object_index import build_vcp_object_index


class CountingObjects:
    def __init__(self, objects):
        self.objects, self.scans = objects, 0

    def __iter__(self):
        self.scans += 1
        return iter(self.objects)

    def link(self, obj):
        self.objects.link(obj)


def fixture():
    owner = root()
    collection = mirrors._ensure_vcp_collection(bpy.context.scene)
    muscle = SimpleNamespace(fiber_refs=[SimpleNamespace(fiber_id='F')])
    fiber = dict(af_authoring_symmetry='native_mirror', af_authoring_mirror_axis='X',
                 af_authoring_mirror_origin=(0., 0., 0.))
    return owner, collection, {'M': muscle}, {'F': fiber}


def surface(collection, owner, name, mid='M', role='BASE', mirrored=False):
    obj = mesh_object(name)
    collection.objects.link(obj)
    obj['af_root_name'], obj['af_muscle_id'], obj['af_muscle_surface'] = owner.name, mid, role
    obj['af_muscle_proxy'] = True
    if mirrored: mirrors._tag_muscle_mirror(obj, owner.name, mid, role)
    return obj


def sync(values, targets=None):
    owner, collection, muscles, fibers = values
    mirrors._sync_muscle_mirrors(owner, collection, muscles, fibers, {}, targets)


def index(values):
    return build_vcp_object_index(values[1], values[0].name, first_match=True)


class MirrorIndexTests(BlenderTestCase):
    def test_absent_surfaces_do_not_rescan_per_muscle(self):
        owner, collection, muscles, fibers = fixture()
        counted = CountingObjects(collection.objects)
        muscles = {str(i): muscles['M'] for i in range(100)}
        sync((owner, SimpleNamespace(objects=counted), muscles, fibers))
        self.assertEqual(counted.scans, 2)  # One index build and one stale-object sweep.

    def test_duplicates_keep_existing_first_match_selection(self):
        values = fixture(); owner, collection, _, _ = values
        first = surface(collection, owner, 'A_source'); surface(collection, owner, 'B_source')
        mirror = surface(collection, owner, 'A_mirror', mirrored=True)
        duplicate = surface(collection, owner, 'B_mirror', mirrored=True); untouched = duplicate.data
        sync(values)
        self.assertEqual(mirror.data, first.data)
        self.assertEqual(duplicate.data, untouched)
        self.assertEqual(index(values)['muscle'][('M', 'BASE')], first)
        self.assertNotEqual(build_vcp_object_index(collection, owner.name)['muscle'][('M', 'BASE')], first)

    def test_create_and_retype_keep_index_current(self):
        values = fixture(); owner, collection, _, _ = values
        source = surface(collection, owner, 'Source'); lookup = index(values); key = ('M', 'BASE')
        wrong = bpy.data.objects.new('WrongType', bpy.data.curves.new('WrongType', 'CURVE'))
        collection.objects.link(wrong); mirrors._tag_muscle_mirror(wrong, owner.name, *key)
        lookup = index(values); previous = wrong.session_uid
        self.assertTrue(mirrors._sync_muscle_surface(owner, collection, key, ('X', (0, 0, 0)), lookup))
        result = lookup['muscle_mirror'][key]
        self.assertNotEqual(result.session_uid, previous); self.assertEqual(result.data, source.data)
        self.assertTrue(mirrors._sync_muscle_surface(owner, collection, ('M', 'INFL'), None, lookup) is False)
        mirrors._sync_muscle_surface(owner, collection, key, ('X', (0, 0, 0)), lookup)
        self.assertEqual(lookup['muscle_mirror'][key], result)

    def test_targeted_removal_preserves_other_ids_roots_and_roles(self):
        values = fixture(); owner, collection, _, _ = values
        doomed = surface(collection, owner, 'Doomed', mirrored=True); name = doomed.name
        other = surface(collection, owner, 'Other', mid='Other', mirrored=True)
        foreign = surface(collection, SimpleNamespace(name='Foreign'), 'Foreign', mirrored=True)
        custom = surface(collection, owner, 'Custom', role='CUSTOM', mirrored=True)
        lookup = index(values)
        mirrors._sync_muscle_mirrors(owner, collection, {}, {}, {}, {'M'}, lookup)
        self.assertNotIn(name, bpy.data.objects); self.assertNotIn(('M', 'BASE'), lookup['muscle_mirror'])
        self.assertTrue(all(o.name in bpy.data.objects for o in (other, foreign, custom)))

    def test_bilateral_surface_removes_generated_partners(self):
        values = fixture(); owner, collection, muscles, _ = values
        surface(collection, owner, 'Source'); sync(values)
        self.assertIn(('M', 'BASE'), index(values)['muscle_mirror'])
        muscles['M'].use_mirrored_rows = True; sync(values, {'M'})
        self.assertFalse(index(values)['muscle_mirror'])

    def test_full_cleanup_handles_legacy_mirror_tags(self):
        values = fixture(); owner, collection, _, _ = values
        legacy = surface(collection, owner, 'Legacy', mirrored=True); name = legacy.name
        del legacy['af_source_muscle_id']; sync(values)
        self.assertNotIn(name, bpy.data.objects)

    def test_next_pass_sees_replaced_source(self):
        values = fixture(); owner, collection, _, _ = values
        source = surface(collection, owner, 'Source'); sync(values)
        mirror = index(values)['muscle_mirror'][('M', 'BASE')]; identity = mirror.session_uid
        remove_obj(source); replacement = surface(collection, owner, 'Replacement'); sync(values)
        self.assertEqual(mirror.session_uid, identity); self.assertEqual(mirror.data, replacement.data)

    def test_fiber_creation_and_deletion_update_the_same_index(self):
        values = fixture(); owner, collection, _, fibers = values
        source = bpy.data.objects.new('Fiber', bpy.data.curves.new('Fiber', 'CURVE'))
        collection.objects.link(source)
        for key, value in dict(af_root_name=owner.name, af_fiber_proxy=True, af_fiber_id='F',
                              af_fiber_output_state='CURRENT').items(): source[key] = value
        lookup = index(values)
        mirrors._sync_fiber_mirrors(owner, collection, fibers, {}, {'F'}, lookup)
        mirror = lookup['fiber_mirror']['F']; name = mirror.name
        self.assertEqual(mirror.data, source.data)
        mirrors._sync_fiber_mirrors(owner, collection, {}, {}, {'F'}, lookup)
        self.assertNotIn('F', lookup['fiber_mirror']); self.assertNotIn(name, bpy.data.objects)

    def test_orphan_cleanup_preserves_live_mesh_and_curve_users(self):
        for pool, args in ((bpy.data.meshes, ()), (bpy.data.curves, ('CURVE',))):
            orphan = pool.new('Unused', *args); name = orphan.name
            _remove_orphan_data(orphan); self.assertNotIn(name, pool)
            data = pool.new('Used', *args); obj = bpy.data.objects.new('User', data)
            _remove_orphan_data(data); self.assertEqual(obj.data, data)
            self.assertIn(data.name, pool)
