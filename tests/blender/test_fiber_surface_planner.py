import math

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, root, scp_with_object
from anthroforge.core.attachment_codec import encode_fiber_surface_param
from anthroforge.core.vcp.fiber_collision import CollisionOracle, _collider_surface
from anthroforge.core.vcp.fiber_planner import PlannerAnchor, SURFACE_LOCAL, plan_route
from anthroforge.core.vcp.fiber_planner_progressive import advance_progressive_plan, begin_progressive_plan
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.runtime_state import fiber_route_mode


def _sphere_fixture():
    root_obj = root()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=2.0)
    scp = scp_with_object(root_obj, "SurfaceOwner", bpy.context.object)
    bpy.context.view_layer.update()
    oracle = CollisionOracle(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get(), 0.002)
    return scp, oracle, oracle.collider_by_id(scp.id)


def _equator_vertices(surface):
    indexed = [(i, point) for i, point in enumerate(surface["verts_world"]) if abs(point.z) < 1.0e-5]
    return sorted(indexed, key=lambda item: math.atan2(item[1].y, item[1].x))


def _vertex_param(surface, vertex):
    tri = next(tri for tri in surface["triangles"] if vertex in tri)
    weights = tuple(1.0 if value == vertex else 0.0 for value in tri)
    return encode_fiber_surface_param({"tri_vidx": tri, "tri_weights": weights})


def _surface_anchors(scp, collider, count=6):
    surface = _collider_surface(collider)
    selected = _equator_vertices(surface)[5:5 + count]
    return [PlannerAnchor(point.copy(), scp.id, _vertex_param(surface, index)) for index, point in selected]


def _finish_progressive(planner):
    while not advance_progressive_plan(planner, 0.0):
        pass
    return planner.result


def _path_length(points):
    return sum((points[index + 1] - points[index]).length for index in range(len(points) - 1))


def _add_route_blocker(root_obj, point):
    bpy.ops.mesh.primitive_cube_add(size=0.3, location=point)
    return scp_with_object(root_obj, "ExternalBlocker", bpy.context.object)


def _preview_fiber(root_obj, anchors):
    fiber = root_obj.af_vcp_system.fibers.add()
    fiber.id, fiber.name = "FIBER_SURFACE", "FIBER_SURFACE"
    fiber.a_parent_id, fiber.a_attach_param = anchors[0].owner_id, anchors[0].attach_raw
    fiber.b_parent_id, fiber.b_attach_param = anchors[-1].owner_id, anchors[-1].attach_raw
    fiber.preview_planner_route, fiber.use_segment_collisions = True, True
    for anchor in anchors[1:-1]:
        touch = fiber.mid_touches.add()
        touch.parent_id, touch.attach_param = anchor.owner_id, anchor.attach_raw
    return fiber


class _SurfaceChoiceOracle:
    clearance = margin = 0.01

    def __init__(self):
        self.owner = {"sid": "OWNER"}

    def active_colliders_for_segment(self, *_args, **_kwargs):
        return (self.owner,)

    def active_colliders_for_polyline(self, *_args, **_kwargs):
        return (self.owner,)

    def collider_by_id(self, _owner_id):
        return self.owner

    def segment_visible(self, *_args, **_kwargs):
        return False

    def surface_local_paths(self, *_args):
        return ([Vector((0.25, 0.3, 0)), Vector((0.75, -0.3, 0))],
                [Vector((0.5, 0.1, 0))])

    def surface_local_path(self, *_args):
        return self.surface_local_paths()[0]

    def surface_route_visible(self, *_args, **_kwargs):
        return True

    def surface_route_shortcut(self, points, *_args):
        return points

    def surface_route_relax(self, points, *_args):
        return points


class FiberSurfacePlannerTests(BlenderTestCase):
    def test_surface_choice_skips_first_safe_zigzag(self):
        raw = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (1, 0, 0)})
        anchors = [PlannerAnchor(Vector((0, 0, 0)), "OWNER", raw),
                   PlannerAnchor(Vector((1, 0, 0)), "OWNER", raw)]
        result = plan_route(_SurfaceChoiceOracle(), anchors, False)
        self.assertEqual((result.mode, len(result.points)), (SURFACE_LOCAL, 3))
        self.assertLess(abs(result.points[1].y), 0.2)

    def test_closed_owner_shortcut_does_not_cross_sphere(self):
        scp, oracle, collider = _sphere_fixture()
        surface = _collider_surface(collider)
        equator = _equator_vertices(surface)
        anchors = [PlannerAnchor(point.copy(), scp.id, _vertex_param(surface, index))
                   for index, point in (equator[0], equator[len(equator) // 2])]
        result = plan_route(oracle, anchors, False)
        self.assertGreater(len(result.points), 2)
        self.assertTrue(oracle.surface_route_visible(result.points, scp.id))

    def test_close_same_owner_anchors_use_local_surface_without_fan(self):
        scp, oracle, collider = _sphere_fixture()
        anchors = _surface_anchors(scp, collider)
        result = plan_route(oracle, anchors, allow_dense=False)
        direct = _path_length([anchor.point for anchor in anchors])
        self.assertEqual((result.mode, result.active_ids), (SURFACE_LOCAL, (scp.id,)))
        self.assertLess(_path_length(result.points) / direct, 3.0)
        self.assertLess(max(point.length for point in result.points), 2.05)

    def test_progressive_and_synchronous_surface_routes_match(self):
        scp, oracle, collider = _sphere_fixture()
        anchors = _surface_anchors(scp, collider)
        expected = plan_route(oracle, anchors, allow_dense=False)
        actual = _finish_progressive(begin_progressive_plan(oracle, anchors, False))
        self.assertEqual((expected.mode, len(expected.points)), (actual.mode, len(actual.points)))
        self.assertLess(max((a - b).length for a, b in zip(expected.points, actual.points)), 1.0e-9)

    def test_surface_routing_can_be_disabled_for_compatibility(self):
        scp, oracle, collider = _sphere_fixture()
        result = plan_route(oracle, _surface_anchors(scp, collider, 2), False, False)
        self.assertNotEqual(result.mode, SURFACE_LOCAL)

    def test_external_collider_rejects_surface_candidate(self):
        scp, oracle, collider = _sphere_fixture()
        anchors = _surface_anchors(scp, collider, 2)
        local = plan_route(oracle, anchors, False)
        blocker = _add_route_blocker(root(), local.points[len(local.points) // 2])
        bpy.context.view_layer.update()
        fresh = CollisionOracle(root(), bpy.context.scene, bpy.context.evaluated_depsgraph_get(), 0.002)
        result = plan_route(fresh, anchors, allow_dense=False)
        self.assertNotEqual(result.mode, SURFACE_LOCAL)
        self.assertIn(blocker.id, result.active_ids)

    def test_solver_preview_publishes_surface_local_route(self):
        scp, oracle, collider = _sphere_fixture()
        fiber = _preview_fiber(root(), _surface_anchors(scp, collider))
        points = FiberSolver().solve_points(root(), fiber, bpy.context.scene,
                                            bpy.context.evaluated_depsgraph_get())
        self.assertEqual(fiber_route_mode(fiber), SURFACE_LOCAL)
        self.assertLess(max(point.length for point in points), 2.05)


if __name__ == "__main__":
    import unittest
    unittest.main()
