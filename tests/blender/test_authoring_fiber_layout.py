"""Read-only point plans use native bindings and current indexed region geometry."""
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from test_authoring_point_picker import cube
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring import attachment_binding, indexed_patches, migration
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.vcp.attachment_backend import resolve_attachment_world
from anthroforge.adapters.authoring.solver import NativeFiberSolver, request_for
from anthroforge.app.authoring.layout_solving import NativeRoute
from anthroforge.app.authoring.fiber_plans import point_record
from anthroforge.core.authoring.layout_reduction import resample
from anthroforge.core.authoring.layout_routing import refine
from anthroforge.core.authoring.model import Budget
from anthroforge.core.authoring.regions import RegionEvaluator
from anthroforge.core.authoring.errors import AuthoringError

REGION = '/skeleton_profiles/default/regions/origin'
LANDMARKS = ('start_left', 'start_right', 'end_right', 'end_left')


def curve_support(obj):
    count = 17
    vertices = [(x, y, z+.5*(1-y*y) if z == 1 else z) for z in (1, -1) for x in (-1, 1) for y in np.linspace(-1, 1, count)]
    top = [(j, j+count, j+count+1, j+1) for j in range(count-1)]
    bottom = [tuple(i+2*count for i in reversed(face)) for face in top]
    boundary = list(range(count))+list(reversed(range(count, 2*count)))
    sides = [(a, a+2*count, b+2*count, b) for a, b in zip(boundary, boundary[1:]+boundary[:1])]
    mesh = bpy.data.meshes.new('Curved layout support')
    mesh.from_pydata(vertices, [], top+bottom+sides)
    mesh.update()
    obj.data = mesh


def document(inventory):
    old = json.loads((Path(__file__).parents[1]/'fixtures/authoring/02-upper-arm.json').read_text())
    value = migration.migrate(old)
    profile, instance = value['skeleton_profiles']['default'], inventory['instances'][0]
    profile['reference_pose'] = inventory['reference_pose']
    for binding in profile['bindings'].values():
        binding.update(scp_id=instance['scp_id'], instance_id=instance['instance_id'])
    for region in profile['regions'].values():
        region['reference_pose'] = inventory['reference_pose']
    geometry = inventory['geometry'][instance['instance_id']]
    vertices = np.asarray(geometry['vertices'])
    selected = [dict(triangle=i, polygon=np.eye(3).tolist()) for i, tri in enumerate(geometry['triangles']) if np.all(vertices[tri, 2] > .99)]
    profile['regions']['origin']['query'] = indexed_patches.bind(geometry, selected)
    validate(value)
    return value


def directed_route(test):
    reference = resample(np.array([[-.8, -.8, 1], [0, .6, 1], [.8, -.8, 1]]), 65)
    domain = RegionEvaluator(test.document, test.inventory).evaluate(REGION)
    hits = test.scene.snap_points(dict(instance_id=test.owner, points=reference[[0, -1]].tolist()), test.inventory)
    points = [point_record(hit, i, 2, REGION) for i, hit in enumerate(hits)]
    fiber = dict(candidate_index=0, across=0., reference_path=reference.tolist(), points=points)
    service = SimpleNamespace(scene=test.scene, solver=NativeFiberSolver(), inventory=test.inventory)
    state = dict(calls=0, budget=Budget(), snapshot=test.scene.capture(test.root.name))
    return NativeRoute(service, dict(region=REGION), domain, fiber, state)


class NativeFiberLayoutTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root = root()
        self.obj = cube(self.root)
        self.scene = StaticScene(self.root, bpy.context.scene)
        self.inventory = self.scene.initialize()
        self.owner = self.inventory['instances'][0]['instance_id']
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.directory, self.store = folder.name, FileStore(folder.name)
        self.document = document(self.inventory)
        self.key = [self.inventory['root_id'], self.document['document_id']]
        self.record = dict(document=self.document, draft_revision=1, receipts={})
        self.store.put('v04_drafts', self.key, self.record)

    def request(self):
        geometry = self.inventory['geometry'][self.owner]
        corners = [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]]
        landmarks = {key: attachment_binding.nearest_binding(geometry, point) for key, point in zip(LANDMARKS, corners)}
        params = dict(scene_id=self.root.name, document_id=self.document['document_id'], expected_scene_revision=self.scene.capture_authoring()['revision'], expected_draft_revision=1, region=REGION, boundary_landmarks=landmarks, tolerance=.01, candidate_count=9, samples_per_fiber=33)
        return dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.plan_fibers', params=params)

    def execute(self, request):
        result = execute(request, self.root, bpy.context.scene, self.directory)
        validate(result, 'protocol')
        return result

    def successful(self, request=None):
        result = self.execute(request or self.request())
        self.assertEqual(result['status'], 'success', result)
        self.assertFalse(result['published'])
        return result['plan']

    def test_read_only_plan_returns_two_native_endpoint_sets(self):
        before = self.scene.capture_authoring()['revision']
        plan = self.successful()
        self.assertEqual((plan['fiber_count'], plan['point_count']), (2, 4))
        self.assertAlmostEqual(plan['region_area'], 4)
        self.assertEqual(self.scene.capture_authoring()['revision'], before)
        self.assertEqual(self.store.get('v04_drafts', self.key), self.record)
        self.assertEqual(len(self.root.af_vcp_system.fibers), 0)
        self.assertEqual(len(self.root.af_vcp_system.muscles), 0)
        self.check_bindings(plan)

    def check_bindings(self, plan):
        for fiber in plan['fibers']:
            for point in fiber['points']:
                attachment = point['attachment']
                native = resolve_attachment_world(self.root, bpy.context.scene, self.owner, attachment['attach_param'])
                np.testing.assert_allclose(native, point['anchor']['point'], atol=1e-6)
                self.assertEqual(attachment['parent_id'], self.obj['af_scp_id'])
                self.assertEqual(point['anchor']['offset'], 0)
                self.assertEqual(point['route_anchor']['region'], REGION)
                self.assertEqual(point['route_anchor']['surface_binding'], point['anchor']['surface_binding'])

    def test_unchanged_request_replays_but_changed_scene_does_not(self):
        request = self.request()
        first = self.successful(request)
        replay = self.execute(request)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['plan'], first)
        self.obj.location.x += .1
        result = self.execute(request)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_SCENE_REVISION')
        self.assertNotIn('plan', result)

    def test_changed_draft_invalidates_cached_plan(self):
        request = self.request()
        self.successful(request)
        self.store.put('v04_drafts', self.key, dict(self.record, draft_revision=2))
        result = self.execute(request)
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_DRAFT_REVISION')
        self.assertNotIn('plan', result)

    def test_indexed_region_and_landmarks_follow_deformation(self):
        request = self.request()
        original = self.successful(request)
        query = deepcopy(self.document['skeleton_profiles']['default']['regions']['origin']['query'])
        for vertex in self.obj.data.vertices:
            vertex.co.z += .25*(vertex.co.x+1)
        self.obj.data.update()
        request.update(request_id=str(uuid4()))
        request['params']['expected_scene_revision'] = self.scene.capture_authoring()['revision']
        deformed = self.successful(request)
        self.assertEqual(deformed['topology_digest'], original['topology_digest'])
        self.assertEqual(self.document['skeleton_profiles']['default']['regions']['origin']['query'], query)
        self.assertAlmostEqual(deformed['boundary_points'][1][2], 1.5)
        self.check_bindings(deformed)

    def test_blocked_planned_anchor_returns_no_usable_plan(self):
        cube(self.root, (0, 0, 1.5))
        self.scene.initialize()
        result = self.execute(self.request())
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(result['diagnostics'][0]['code'], 'LAYOUT_ANCHOR_UNRESOLVED')
        self.assertNotIn('plan', result)

    def test_native_solver_follows_curved_support_without_middle_points(self):
        curve_support(self.obj)
        self.inventory = self.scene.capture_authoring()
        self.document = document(self.inventory)
        self.record = dict(self.record, document=self.document)
        self.store.put('v04_drafts', self.key, self.record)
        plan = self.successful()
        self.assertEqual(plan['fiber_count'], 2)
        self.assertEqual(plan['middle_point_count'], 0)
        self.assertTrue(plan['native_solver_validated'])
        self.assertEqual(plan['solver_calls'], 2)
        for fiber in plan['fibers']:
            self.assertGreater(np.asarray(fiber['solved_path'])[:, 2].max(), 1.45)
        self.check_bindings(plan)

    def test_changed_vertex_topology_requires_region_rebinding(self):
        request = self.request()
        self.obj.data.vertices.add(1)
        self.obj.data.update()
        request['params']['expected_scene_revision'] = self.scene.capture_authoring()['revision']
        result = self.execute(request)
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(result['diagnostics'][0]['code'], 'SURFACE_PATCH_REBIND_REQUIRED')
        self.assertNotIn('plan', result)

    def test_preview_shows_all_points_in_three_coordinate_views(self):
        result = self.execute(self.request())
        self.assertEqual(result['status'], 'success', result)
        preview = Path(result['assets'][0]['path']).read_text(encoding='utf-8')
        self.assertEqual(preview.count('<polyline'), 3*result['plan']['fiber_count'])
        self.assertEqual(preview.count('<circle'), 3*result['plan']['point_count'])
        self.assertIn('Native fibers solved', preview)

    def test_legacy_dense_point_preview_is_not_replayed(self):
        request = self.request()
        self.successful(request)
        key = [self.inventory['root_id'], request['request_id']]
        cached = self.store.get('v04_requests', key)
        cached['response']['plan']['version'] = 'fiber_layout.v1'
        self.store.put('v04_requests', key, cached)
        result = self.execute(request)
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['plan']['version'], 'fiber_layout.v2')
        self.assertNotIn('replayed', result)

    def test_solver_call_budget_is_enforced_without_scene_edits(self):
        request = self.request()
        request['params']['max_solver_calls'] = 1
        result = self.execute(request)
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(result['diagnostics'][0]['code'], 'LAYOUT_SOLVER_CALL_BUDGET')
        self.assertNotIn('plan', result)
        self.assertEqual(len(self.root.af_vcp_system.fibers), 0)

    def test_native_route_adds_one_middle_point_to_steer_a_deliberate_detour(self):
        route = directed_route(self)
        result = refine(route.reference, route.solve, .2, 4, route.state['budget'])
        self.assertTrue(result['validated'])
        self.assertEqual(len(result['controls']), 3)
        self.assertEqual(route.state['calls'], 2)
        self.assertGreater(result['corrections'][0]['before_error'], 1)
        self.assertLess(result['route_max_error'], .2)
        self.assertEqual(result['controls'][1]['anchor']['offset'], 0)
        self.assertIn('surface_binding', result['controls'][1]['anchor'])

    def test_collision_radius_reaches_native_solver_and_cache_key(self):
        self.successful()
        request = self.request()
        request['params'].update(collision_radius=.005, tolerance=.03)
        with patch('anthroforge.adapters.authoring.solver.request_for', wraps=request_for) as calls:
            self.successful(request)
        self.assertEqual(calls.call_count, 2)
        self.assertTrue(all(call.args[0].collision_radius == .005 for call in calls.call_args_list))

    def test_native_timeout_returns_structured_failure_without_legacy_preview_crash(self):
        error = AuthoringError('SOLVER_BUDGET', 'Time budget exhausted')
        error.preview = dict(kind='unpublished_route', points=[[0, 0, 1], [0, 1, 1]])
        with patch.object(NativeFiberSolver, 'solve', side_effect=error):
            result = self.execute(self.request())
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(result['diagnostics'][0]['code'], 'SOLVER_BUDGET')
        self.assertNotIn('plan', result)


if __name__ == '__main__':
    import unittest
    unittest.main()
