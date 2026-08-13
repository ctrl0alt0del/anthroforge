from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
BLENDER_TEST_ROOT = Path(__file__).resolve().parent
for value in (str(BLENDER_TEST_ROOT), str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, root, scp_with_object
from anthroforge.core.vcp import fiber_collision
from anthroforge.core.vcp.fiber_collision import CollisionOracle, _bvh_signed_distance


def _cube_oracle(scale, margin=0.25):
    root_obj = root()
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    obj = bpy.context.active_object
    obj.scale = scale
    scp = scp_with_object(root_obj, "Collider", obj)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    oracle = CollisionOracle(root_obj, bpy.context.scene, depsgraph, margin, 0.002)
    return oracle, next(c for c in oracle.colliders() if c["sid"] == scp.id)


def _cube_scp(root_obj, name, location):
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=location)
    return scp_with_object(root_obj, name, bpy.context.active_object)


def _scene_oracle(root_obj, margin=0.05):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return CollisionOracle(root_obj, bpy.context.scene, depsgraph, margin, 0.002)


def _assert_vector(test, actual, expected):
    for value, target in zip(actual, expected):
        test.assertAlmostEqual(value, target, places=5)


class FiberCollisionTests(BlenderTestCase):
    def test_explicit_empty_collider_cache_is_stable(self):
        oracle = CollisionOracle(root(), bpy.context.scene, None)
        oracle._colliders = []
        with patch.object(fiber_collision, "_build_colliders") as build:
            self.assertEqual(oracle.colliders(), [])
            self.assertEqual(oracle.colliders(), [])
        build.assert_not_called()

    def test_explicit_empty_segments_do_not_run_active_query(self):
        oracle = CollisionOracle(root(), bpy.context.scene, None)
        a, b = Vector((0, 0, 0)), Vector((1, 0, 0))
        error = AssertionError("active query must not run")
        with patch.object(oracle, "active_colliders_for_segment", side_effect=error):
            self.assertTrue(oracle.segment_visible(a, b, colliders=[]))
            self.assertEqual(oracle.segment_hit_samples(a, b, colliders=[]), ())

    def test_explicit_empty_push_does_not_run_active_query(self):
        oracle = CollisionOracle(root(), bpy.context.scene, None)
        point = Vector((1.0, 2.0, 3.0))
        error = AssertionError("active query must not run")
        with patch.object(oracle, "active_colliders_for_polyline", side_effect=error):
            pushed, penetration = oracle.push_out_point(point, colliders=[])
        _assert_vector(self, pushed, point)
        self.assertEqual(penetration, 0.0)

    def test_uniform_scale_uses_world_distance_and_margin(self):
        oracle, collider = _cube_oracle((3.0, 3.0, 3.0))
        point = Vector((3.1, 0.0, 0.0))
        self.assertAlmostEqual(_bvh_signed_distance(collider, point), 0.1, places=5)
        pushed, penetration = oracle.push_out_point(point, [collider])
        _assert_vector(self, pushed, (3.25, 0.0, 0.0))
        self.assertAlmostEqual(penetration, 0.15, places=5)

    def test_nonuniform_scale_uses_world_distance_and_margin(self):
        oracle, collider = _cube_oracle((2.0, 0.5, 1.5))
        point = Vector((0.0, 0.6, 0.0))
        self.assertAlmostEqual(_bvh_signed_distance(collider, point), 0.1, places=5)
        pushed, penetration = oracle.push_out_point(point, [collider])
        _assert_vector(self, pushed, (0.0, 0.75, 0.0))
        self.assertAlmostEqual(penetration, 0.15, places=5)

    def test_exact_push_skips_redundant_voxel_precheck(self):
        oracle, collider = _cube_oracle((1.0, 1.0, 1.0))
        with patch.object(fiber_collision, "_voxel_signed_distance", side_effect=AssertionError):
            pushed, penetration = oracle.push_out_point(Vector((1.1, 0.0, 0.0)), [collider])
        _assert_vector(self, pushed, (1.25, 0.0, 0.0))
        self.assertAlmostEqual(penetration, 0.15, places=5)

    def test_negative_scale_preserves_inside_sign_and_outward_push(self):
        oracle, collider = _cube_oracle((-2.0, 0.5, 1.5))
        point = Vector((1.9, 0.0, 0.0))
        self.assertAlmostEqual(_bvh_signed_distance(collider, point), -0.1, places=5)
        pushed, penetration = oracle.push_out_point(point, [collider])
        _assert_vector(self, pushed, (2.25, 0.0, 0.0))
        self.assertAlmostEqual(penetration, 0.35, places=5)

    def test_negative_scale_preserves_outside_sign(self):
        _oracle, collider = _cube_oracle((-2.0, 0.5, 1.5))
        distance = _bvh_signed_distance(collider, Vector((2.1, 0.0, 0.0)))
        self.assertAlmostEqual(distance, 0.1, places=5)

    def test_collider_lookup_is_built_once(self):
        oracle, collider = _cube_oracle((1.0, 1.0, 1.0))
        wrapped = fiber_collision._build_collider_lookup
        with patch.object(fiber_collision, "_build_collider_lookup", wraps=wrapped) as build:
            self.assertIs(oracle.collider_by_id(collider["sid"]), collider)
            self.assertIs(oracle.collider_by_id(collider["sid"]), collider)
        self.assertEqual(build.call_count, 1)

    def test_same_owner_open_surface_chord_is_not_globally_exempt(self):
        root_obj = root()
        bpy.ops.mesh.primitive_plane_add(size=2.0)
        scp = scp_with_object(root_obj, "OpenOwner", bpy.context.active_object)
        oracle = _scene_oracle(root_obj)
        collider = oracle.collider_by_id(scp.id)
        chord = Vector((-0.9, 0.0, 0.0)), Vector((0.9, 0.0, 0.0))
        outward = Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))
        self.assertFalse(oracle.segment_visible(*chord, (scp.id, scp.id), (collider,)))
        self.assertTrue(oracle.segment_visible(*outward, (scp.id, ""), (collider,)))

    def test_mixed_owner_endpoint_zones_do_not_hide_third_blocker(self):
        root_obj = root()
        left = _cube_scp(root_obj, "LeftOwner", (-2.0, 0.0, 0.0))
        right = _cube_scp(root_obj, "RightOwner", (2.0, 0.0, 0.0))
        blocker = _cube_scp(root_obj, "MiddleBlocker", (0.0, 0.0, 0.0))
        oracle = _scene_oracle(root_obj)
        colliders = tuple(oracle.collider_by_id(item.id) for item in (left, right, blocker))
        a, b = Vector((-1.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0))
        self.assertFalse(oracle.segment_visible(a, b, (left.id, right.id), colliders))

    def test_mixed_owner_endpoint_zones_allow_clear_departure_and_arrival(self):
        root_obj = root()
        left = _cube_scp(root_obj, "LeftOwner", (-2.0, 0.0, 0.0))
        right = _cube_scp(root_obj, "RightOwner", (2.0, 0.0, 0.0))
        oracle = _scene_oracle(root_obj)
        colliders = tuple(oracle.collider_by_id(item.id) for item in (left, right))
        a, b = Vector((-1.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0))
        self.assertTrue(oracle.segment_visible(a, b, (left.id, right.id), colliders))

    def test_query_caches_are_bounded(self):
        oracle = CollisionOracle(root(), bpy.context.scene, None)
        with patch.object(fiber_collision, "_QUERY_CACHE_LIMIT", 2):
            for index in range(4):
                point = Vector((float(index), 0.0, 0.0))
                oracle.push_out_point(point, colliders=[])
                oracle.segment_hit_samples(point, point + Vector((1, 0, 0)), colliders=[])
        self.assertLessEqual(len(oracle._push_cache), 2)
        self.assertLessEqual(len(oracle._segment_hit_cache), 2)

    def test_active_queries_reuse_oracle_local_bounds(self):
        oracle = CollisionOracle(root(), bpy.context.scene, None, margin=0.1)
        collider = {"sid": "C", "stamp": (1,), "mn": Vector((-1, -1, -1)), "mx": Vector((1, 1, 1))}
        oracle._colliders = (collider,)
        points = (Vector((0, 0, 0)), Vector((1, 0, 0)))
        with patch.object(fiber_collision, "_active_for_bounds", return_value=[collider]) as active:
            first = oracle.active_colliders_for_polyline(points)
            second = oracle.active_colliders_for_segment(*points)
        self.assertIs(first, second)
        self.assertEqual(active.call_count, 1)

    def test_active_query_local_cache_is_bounded(self):
        oracle = CollisionOracle(root(), bpy.context.scene, None)
        oracle._colliders = ()
        with patch.object(fiber_collision, "_ACTIVE_LOCAL_CACHE_LIMIT", 2), \
             patch.object(fiber_collision, "_active_for_bounds", return_value=[]):
            for index in range(4):
                oracle.active_colliders_for_polyline((Vector((index, 0, 0)),))
        self.assertEqual(len(oracle._active_cache), 2)

    def test_voxel_payload_cache_is_local_and_bounded(self):
        _oracle, collider = _cube_oracle((1.0, 1.0, 1.0))
        scene = bpy.context.scene
        with patch.object(fiber_collision, "_VOXEL_PAYLOAD_LIMIT", 2):
            first = fiber_collision._voxel_payload(scene, collider, 0.1)
            fiber_collision._voxel_payload(scene, collider, 0.2)
            self.assertIs(fiber_collision._voxel_payload(scene, collider, 0.1), first)
            fiber_collision._voxel_payload(scene, collider, 0.3)
        self.assertEqual(tuple(collider["_voxel_cache"]), (0.1, 0.3))

    def test_voxel_sample_cache_is_bounded(self):
        _oracle, collider = _cube_oracle((1.0, 1.0, 1.0))
        scene = bpy.context.scene
        payload = fiber_collision._voxel_payload(scene, collider, 0.1)
        with patch.object(fiber_collision, "_VOXEL_VALUE_LIMIT", 2):
            for index in range(4):
                base = (index, 0, 0)
                fiber_collision._grid_value(scene, collider, payload, base, 0, 0, 0)
        self.assertLessEqual(len(payload["values"]), 2)


if __name__ == "__main__":
    import unittest
    unittest.main(argv=[__file__])
