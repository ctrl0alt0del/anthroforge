"""Independent projection, z-buffer and image contract checks."""
import unittest
import numpy as np
from core.authoring import visual_camera as camera, visual_mesh as mesh, visual_raster as raster, visual_images as images
from core.authoring import visual_pick
from core.authoring import visual_selection as selection
from core.authoring import surface_patch, substrate
from core.authoring.model import Budget
from core.authoring.errors import AuthoringError


def geometry():
    vertices = [[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]
    return dict(vertices=vertices, triangles=faces, matrix=np.eye(4).tolist())


def scene():
    return dict(owner='cube', geometry={'cube': geometry()})


class VisualTests(unittest.TestCase):
    def test_coincident_triangles_keep_distinct_patch_identity(self):
        value = geometry()
        value['triangles'].append(list(value['triangles'][0]))
        patches = [dict(triangle=len(value['triangles'])-1, polygon=np.eye(3).tolist())]
        query = dict(topology_digest=mesh.topology(value), patches=patches)
        chart = substrate.box_frame(dict(axes=np.eye(3)), dict(instance_id='cube'), value)
        inside, _ = surface_patch.partition(list(substrate.surface(chart)), query, chart, Budget())
        area = sum(selection.clipping.area(substrate.world(chart, p)) for p in inside)
        self.assertAlmostEqual(area, selection.area(value, patches), places=8)

    def test_clipped_surface_retains_patch_correspondence(self):
        value = geometry()
        patches = [dict(triangle=0, polygon=np.eye(3).tolist())]
        query = dict(topology_digest=mesh.topology(value), patches=patches)
        chart = substrate.box_frame(dict(axes=np.eye(3)), dict(instance_id='cube'), value)
        triangle = substrate.surface(chart)[0]
        polygon = (triangle+triangle[0])/2
        inside, outside = surface_patch.partition([polygon], query, chart, Budget())
        self.assertAlmostEqual(sum(selection.clipping.area(p) for p in inside), selection.clipping.area(polygon), places=8)
        self.assertEqual(outside, [])

    def test_adopted_patch_matches_selection_and_requires_topology(self):
        value = geometry()
        view = dict(camera=camera.make(value, [0, 0, 1]))
        patches = selection.select(scene(), view, [[.4, .4], [.6, .4], [.6, .6], [.4, .6]])
        query = dict(topology_digest=mesh.topology(value), patches=patches)
        chart = substrate.box_frame(dict(axes=np.eye(3)), dict(instance_id='cube'), value)
        inside, _ = surface_patch.partition(list(substrate.surface(chart)), query, chart, Budget())
        actual = sum(selection.clipping.area(substrate.world(chart, p)) for p in inside)
        self.assertAlmostEqual(actual, selection.area(value, patches), places=8)
        value['triangles'] = value['triangles'][::-1]
        with self.assertRaisesRegex(AuthoringError, 'Surface patch rebind required'):
            surface_patch.partition(list(substrate.surface(chart)), query, chart, Budget())

    def test_polygon_clips_partial_faces_and_excludes_back(self):
        view = dict(camera=camera.make(geometry(), [0, 0, 1], 128))
        polygon = [[.4, .4], [.6, .4], [.6, .6], [.4, .6]]
        patches = selection.select(scene(), view, polygon)
        polygons = selection.world_polygons(geometry(), patches)
        self.assertTrue(polygons)
        self.assertTrue(all(np.allclose(p[:, 2], 1) for p in polygons))
        self.assertAlmostEqual(selection.area(geometry(), patches), (.2*view['camera']['span'])**2, places=8)

    def test_patch_union_and_subtraction_do_not_duplicate_area(self):
        view = dict(camera=camera.make(geometry(), [0, 0, 1], 128))
        patches = selection.select(scene(), view, [[.4, .4], [.6, .4], [.6, .6], [.4, .6]])
        combined = selection.combine(patches, patches, 'add')
        self.assertAlmostEqual(selection.area(geometry(), patches), selection.area(geometry(), combined), places=8)
        self.assertAlmostEqual(selection.area(geometry(), selection.combine(patches, patches, 'subtract')), 0, places=8)

    def test_overlapping_patches_have_union_area(self):
        view = dict(camera=camera.make(geometry(), [0, 0, 1], 128))
        a = selection.select(scene(), view, [[.4, .4], [.6, .4], [.6, .6], [.4, .6]])
        b = selection.select(scene(), view, [[.5, .4], [.7, .4], [.7, .6], [.5, .6]])
        union = selection.combine(a, b, 'add')
        self.assertAlmostEqual(selection.area(geometry(), union), .3*.2*view['camera']['span']**2, places=8)

    def test_neighbor_occludes_selection(self):
        data = scene()
        other = geometry()
        other['matrix'][2][3] = 3
        data['geometry']['occluder'] = other
        view = dict(camera=camera.make(geometry(), [0, 0, 1], 128))
        self.assertEqual(selection.select(data, view, [[.4, .4], [.6, .4], [.6, .6], [.4, .6]]), [])

    def test_pick_matches_pixel_and_reconstructs_triangle(self):
        view = dict(id='v', snapshot_id='s', camera=camera.make(geometry(), [1, 1, 1], 128))
        data = dict(scene(), scene_revision='r')
        buffer = raster.render(data, view['camera'])
        for x, y in [(64, 64), (54, 69), (72, 60)]:
            hit = visual_pick.pick(data, view, [(x+.5)/128, (y+.5)/128])
            self.assertTrue(hit['hit'])
            self.assertEqual(hit['triangle'], buffer['ids'][y, x])
            triangle = buffer['mesh'][hit['triangle']]
            np.testing.assert_allclose(np.asarray(hit['barycentric']) @ triangle, hit['point'], atol=1e-12)

    def test_background_and_occluded_confirmation(self):
        data = dict(scene(), scene_revision='r')
        front = dict(id='f', snapshot_id='s', camera=camera.make(geometry(), [1, 0, 0], 128))
        back = dict(id='b', snapshot_id='s', camera=camera.make(geometry(), [-1, 0, 0], 128))
        hit = visual_pick.pick(data, front, [.5, .5])
        self.assertFalse(visual_pick.pick(data, front, [0, 0])['hit'])
        self.assertEqual(visual_pick.project_hit(data, front, hit)['state'], 'visible')
        self.assertEqual(visual_pick.project_hit(data, back, hit)['state'], 'occluded')

    def test_all_camera_roundtrips_and_handedness(self):
        for direction in camera.DIRECTIONS.values():
            view = camera.make(geometry(), direction, 128)
            points = np.array([[.2, -.4, 1], [1, 1, 1], [-1, -1, -1]])
            np.testing.assert_allclose(camera.unproject(view, camera.project(view, points)), points, atol=1e-12)
            np.testing.assert_allclose(np.cross(view['right'], view['up']), -np.array(view['forward']), atol=1e-12)

    def test_proportions_do_not_collapse_oblique_view_angle(self):
        value = geometry()
        value['matrix'][0][0] = 40
        original = camera.make(geometry(), [1, 1, 1])
        changed = camera.make(value, [1, 1, 1])
        np.testing.assert_allclose(original['forward'], changed['forward'])

    def test_opposite_view_patches_combine_on_distinct_surfaces(self):
        polygon = [[.4, .4], [.6, .4], [.6, .6], [.4, .6]]
        a = selection.select(scene(), dict(camera=camera.make(geometry(), [0, 0, 1])), polygon)
        b = selection.select(scene(), dict(camera=camera.make(geometry(), [0, 0, -1])), polygon)
        both = selection.combine(a, b, 'add')
        self.assertAlmostEqual(selection.area(geometry(), both), selection.area(geometry(), a)*2, places=8)

    def test_opposite_views_show_opposite_faces(self):
        observed = []
        for direction in ([1, 0, 0], [-1, 0, 0]):
            view = camera.make(geometry(), direction, 128)
            image = raster.render(scene(), view)
            face = image['mesh'][image['ids'][64, 64]]
            observed.append(float(face[:, 0].mean()))
            self.assertTrue(np.isfinite(image['depth'][64, 64]))
        self.assertEqual(observed, [1., -1.])

    def test_section_reveals_opposite_wall(self):
        view = camera.make(geometry(), [1, 0, 0], 128)
        image = raster.render(scene(), view, dict(normal=[1, 0, 0], distance=0))
        face = image['mesh'][image['ids'][64, 64]]
        self.assertEqual(float(face[:, 0].mean()), -1)

    def test_lossless_png_header(self):
        view = camera.make(geometry(), [1, 1, 1], 128)
        pixels = raster.shade(raster.render(scene(), view), view, 'cube')
        self.assertEqual(pixels.shape, (128, 128, 3))
        self.assertTrue(images.png(pixels).startswith(b'\x89PNG\r\n\x1a\n'))
