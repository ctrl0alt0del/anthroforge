"""Public API, actual native bases, transforms, mirrors and failure completeness."""
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, root
from test_muscle_section_profile import fixture
from anthroforge.app.authoring.api import execute
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def readonly_journal():
    return nullcontext(str(Path(__file__).parent))


def call(owner, journal, **params):
    return execute(dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request',
        request_id=str(uuid4()), op='muscles.base_intersections', params=dict(scene_id=owner.name, **params)),
        owner, bpy.context.scene, journal)


def base(owner, name, points):
    with suppress_vcp_prop_updates():
        muscle = owner.af_vcp_system.muscles.add(); muscle.id = name; muscle.name = name
    mesh = bpy.data.meshes.new(name); mesh.from_pydata(points, [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh); bpy.context.scene.collection.objects.link(obj)
    for key, value in dict(af_root_name=owner.name, af_muscle_proxy=True, af_muscle_surface='BASE', af_muscle_id=name).items(): obj[key] = value
    return obj


def pair(owner):
    a = base(owner, 'First', [(-2, -2, 0), (2, -2, 0), (0, 2, 0)])
    b = base(owner, 'Second', [(0, -.5, -1), (0, -.5, 1), (0, 1, 0)])
    return a, b


class AuthoringBaseIntersectionTests(BlenderTestCase):
    def test_hidden_bases_without_inflation_and_group_filter(self):
        owner = root(); a, b = pair(owner); a.hide_set(True); b.hide_render = True
        for m in owner.af_vcp_system.muscles: m['af_pair_group_id'] = 'same'
        with readonly_journal() as journal:
            result = call(owner, journal); self.assertEqual(result['status'], 'success', result)
            report = result['entities'][0]['intersections']
            self.assertEqual(report['intersection_pair_count'], 1); self.assertEqual(report['surface_count'], 2)
            self.assertEqual(report['pairs'][0]['first']['object_name'], a.name)
            self.assertTrue(a.hide_get()); self.assertTrue(b.hide_render); self.assertFalse(result['published'])

    def test_live_transform_no_cached_response(self):
        owner = root(); a, b = pair(owner)
        with readonly_journal() as journal:
            first = call(owner, journal); b.location.x = 10
            second = call(owner, journal); report = second['entities'][0]['intersections']
            self.assertEqual(report['pairs'], [])
            self.assertNotEqual(report['geometry_revision'], first['entities'][0]['intersections']['geometry_revision'])
            stale = call(owner, journal, expected_scene_revision='old'); self.assertEqual(stale['status'], 'unresolved')

    def test_mirror_cross_source_included_and_can_be_filtered(self):
        owner = root(); a, b = pair(owner); mirror = a.copy(); mirror.data = a.data
        mirror['af_muscle_mirror_proxy'] = True; mirror['af_source_muscle_id'] = 'First'
        bpy.context.scene.collection.objects.link(mirror)
        with readonly_journal() as journal:
            result = call(owner, journal)['entities'][0]['intersections']
            self.assertEqual(result['surface_count'], 3); self.assertEqual(result['intersection_pair_count'], 3)
            result = call(owner, journal, include_mirrors=False)['entities'][0]['intersections']
            self.assertEqual(result['surface_count'], 2)

    def test_missing_stale_duplicate_and_empty_base_are_incomplete(self):
        owner = root(); a, b = pair(owner)
        with readonly_journal() as journal:
            for state in ('STALE', 'INVALID'):
                b['af_muscle_output_state'] = state; result = call(owner, journal)
                self.assertEqual(result['status'], 'unresolved'); self.assertFalse(result['entities'][0]['intersections']['complete'])
            b['af_muscle_output_state'] = 'CURRENT'; duplicate = b.copy(); bpy.context.scene.collection.objects.link(duplicate)
            report = call(owner, journal)['entities'][0]['intersections']; self.assertEqual(report['issues'][0]['code'], 'BASE_DUPLICATE')
            bpy.data.objects.remove(duplicate, do_unlink=True); bpy.data.objects.remove(b, do_unlink=True)
            report = call(owner, journal)['entities'][0]['intersections']; self.assertEqual(report['issues'][0]['code'], 'BASE_MISSING')

    def test_actual_native_base_read_does_not_rebuild(self):
        owner, _, muscle = fixture(); objects = [(o.name, o.data) for o in bpy.context.scene.objects]
        from anthroforge.core.visualization.muscle_sync import register_muscle_sync
        with readonly_journal() as journal, patch.object(register_muscle_sync(), '_collect_points_with_fallback', side_effect=AssertionError('reroute')):
            result = call(owner, journal); self.assertEqual(result['status'], 'success', result)
            self.assertEqual(result['entities'][0]['intersections']['surface_count'], 1)
            self.assertEqual(objects, [(o.name, o.data) for o in bpy.context.scene.objects])

    def test_selection_and_schema_validation(self):
        owner = root(); pair(owner)
        with readonly_journal() as journal:
            report = call(owner, journal, muscle_ids=['First'])['entities'][0]['intersections']
            self.assertEqual(report['surface_count'], 1); self.assertEqual(report['pairs'], [])
            for params in (dict(muscle_ids=['missing']), dict(witness_limit=-1), dict(tolerance=0)):
                self.assertEqual(call(owner, journal, **params)['status'], 'unresolved')

    def test_orphan_and_degenerate_geometry_not_clean(self):
        owner = root(); a, b = pair(owner); b['af_muscle_id'] = 'orphan'
        with readonly_journal() as journal:
            report = call(owner, journal)['entities'][0]['intersections']
            self.assertFalse(report['complete']); self.assertEqual(report['issues'][0]['code'], 'BASE_ORPHAN')
            b['af_muscle_id'] = 'Second'; b.data.vertices[1].co = b.data.vertices[0].co
            result = call(owner, journal); self.assertEqual(result['status'], 'unresolved')
            self.assertEqual(result['entities'][0]['intersections']['issues'][0]['code'], 'BASE_DEGENERATE_TRIANGLES')

    def test_no_journal_writes_and_unavailable_native(self):
        from anthroforge.core.authoring.storage import FileStore
        owner = root(); pair(owner)
        with readonly_journal() as journal, patch.object(FileStore, 'put', side_effect=AssertionError('journal write')):
            self.assertEqual(call(owner, journal)['status'], 'success')
            with patch('anthroforge.core.authoring.base_intersections.library', side_effect=RuntimeError('BASE_INTERSECTIONS_NATIVE_UNAVAILABLE')):
                result = call(owner, journal); self.assertEqual(result['status'], 'unresolved')
                self.assertEqual(result['diagnostics'][0]['code'], 'BASE_INTERSECTIONS_NATIVE_UNAVAILABLE')
