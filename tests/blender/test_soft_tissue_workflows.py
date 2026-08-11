import unittest
import json
import os
from unittest.mock import patch

import bpy
from mathutils import Vector

from app.runtime_api import sync_scene
from core.deps.dirty_hints import dirty_hints_for
from core.vcp.runtime_state import soft_tissue_status
from core.vcp.soft_tissue_static_pouch import mesh_volume, triangulate_faces
from tests.blender._helpers import ensure_addon_registered, reset_scene, root, scp_with_object
from anthroforge.app.use_cases.soft_tissue_create import create_soft_tissue_vcp
from anthroforge.app.use_cases.soft_tissue_convert import convert_blob_to_soft_tissue
from anthroforge.app.use_cases.vcp_delete import delete_vcp_in_tree


class SoftTissueWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_addon_registered()

    def setUp(self):
        reset_scene()

    def test_closed_bulk_creates_owned_point_and_static_meshes(self):
        tissue = _create_point_tissue()
        self.assertEqual((tissue.base_domain, tissue.base_object_ref.type), ("POINT", "EMPTY"))
        self.assertTrue(tissue.base_object_ref.get("af_soft_tissue_base"))
        self.assertIsNotNone(_proxy(tissue.id))
        self.assertIsNotNone(_rest_proxy(tissue.id))
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_surface_base_follows_scp_without_recapture(self):
        host, scp, base, tissue = _create_surface_tissue()
        before = (base.matrix_world @ base.data.vertices[0].co).z
        for vertex in host.data.vertices:
            vertex.co.z += 0.4
        host.data.update()
        sync_scene(root(), bpy.context.scene, dirty_hints_for("SCP", {scp.id}))
        after = (base.matrix_world @ base.data.vertices[0].co).z
        self.assertAlmostEqual(after - before, 0.4, places=5)
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_surface_mode_and_domain_cannot_diverge(self):
        _host, _scp, _base, tissue = _create_surface_tissue()
        tissue.inflation_mode = "RADIAL"
        self.assertEqual((tissue.base_domain, tissue.inflation_mode), ("SURFACE", "NORMAL"))

    def test_scp_transform_event_updates_surface_tissue(self):
        host, _scp, base, tissue = _create_surface_tissue()
        from anthroforge.core.visualization import sync_runner
        from anthroforge.core.visualization.sync import register_sync
        register_sync()
        sync_runner.clear_pending_runtime()
        before = (_centroid_x(base), _centroid_x(_proxy(tissue.id)))
        with patch.dict(os.environ, {"AF_DEPS_DEFER": "0"}):
            host.location.x += 0.4
            bpy.context.view_layer.update()
            sync_runner._flush_pending()
        after = (_centroid_x(base), _centroid_x(_proxy(tissue.id)))
        self.assertEqual(tuple(round(a - b, 5) for a, b in zip(after, before)), (0.4, 0.4))

    def test_layer_rest_shape_preserves_accepted_thickness_range(self):
        tissue = _create_grid_tissue("LAYER")
        rest = _rest_proxy(tissue.id)
        count = len(tissue.base_object_ref.data.vertices)
        values = [(rest.data.vertices[i].co - rest.data.vertices[count + i].co).length for i in range(count)]
        self.assertAlmostEqual(min(values), 0.008, places=6)
        self.assertAlmostEqual(max(values), 0.28, places=6)

    def test_surface_inflation_keeps_base_normals_at_sharp_host_corners(self):
        host, base = _cube("Sharp Host"), _x_quad("Sharp Base")
        scp_with_object(root(), "Sharp Host", host)
        scene = bpy.context.scene
        scene.af_new_soft_tissue_preset = "LAYER"
        scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
        self.assertTrue(create_soft_tissue_vcp(bpy.context).ok)
        tissue = root().af_vcp_system.soft_tissues[-1]
        rest = _rest_proxy(tissue.id)
        count = len(rest.data.vertices) // 2
        deltas = [rest.data.vertices[index].co - rest.data.vertices[count + index].co for index in range(count)]
        self.assertTrue(all(abs(delta.normalized().x) > 0.999 for delta in deltas))

    def test_boundary_only_surface_is_refined_for_sagginess(self):
        host, base = _cube("Sag Host"), _x_quad("Sag Base")
        scp_with_object(root(), "Sag Host", host)
        scene = bpy.context.scene
        scene.af_new_soft_tissue_preset = "POUCH"
        scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
        self.assertTrue(create_soft_tissue_vcp(bpy.context).ok)
        tissue = root().af_vcp_system.soft_tissues[-1]
        zero = _solve_with_sagginess(tissue, 0.0)
        sagged = _solve_with_sagginess(tissue, 1.0)
        self.assertGreater(len(zero), len(base.data.vertices) * 2)
        self.assertGreater(max((Vector(a) - Vector(b)).length for a, b in zip(zero, sagged)), 1.0e-3)

    def test_vertical_pouch_sags_from_first_free_band_without_rising(self):
        host, base = _cube("Envelope Host"), _x_quad("Envelope Base")
        scp_with_object(root(), "Envelope Host", host)
        scene = bpy.context.scene
        scene.af_new_soft_tissue_preset = "POUCH"
        scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
        self.assertTrue(create_soft_tissue_vcp(bpy.context).ok)
        tissue = root().af_vcp_system.soft_tissues[-1]
        rest, final = _rest_proxy(tissue.id), _proxy(tissue.id)
        fixed, count, edges = _surface_constraint_data(tissue)
        near = _first_free_band(fixed, count, edges)
        gravity = Vector(tissue.gravity).normalized()
        drops = [(final.data.vertices[i].co - rest.data.vertices[i].co).dot(gravity)
                 for i in range(count)]
        self.assertGreater(len(near), 0)
        self.assertGreaterEqual(min(drops), -1.0e-6)
        self.assertGreater(sum(drops[i] for i in near) / len(near), 1.0e-4)

    def test_artist_painted_inflation_field_is_preserved(self):
        host = _quad("Paint Host", 0.0)
        scp_with_object(root(), "Paint Host", host)
        base = _grid("Painted Base", 5)
        group = base.vertex_groups.new(name="AF_ST_INFLATION")
        expected = tuple(index / (len(base.data.vertices) - 1) for index in range(len(base.data.vertices)))
        for index, weight in enumerate(expected):
            group.add([index], weight, "REPLACE")
        scene = bpy.context.scene
        scene.af_new_soft_tissue_preset = "LAYER"
        scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
        self.assertTrue(create_soft_tissue_vcp(bpy.context).ok)
        actual = tuple(group.weight(index) for index in range(len(base.data.vertices)))
        self.assertLess(max(abs(a - b) for a, b in zip(actual, expected)), 1.0e-6)

    def test_pouch_static_solve_applies_gravity_and_retains_volume(self):
        tissue = _create_grid_tissue("POUCH")
        rest, final = _rest_proxy(tissue.id), _proxy(tissue.id)
        faces = tuple(tuple(poly.vertices) for poly in rest.data.polygons)
        rest_points = tuple(tuple(vertex.co) for vertex in rest.data.vertices)
        final_points = tuple(tuple(vertex.co) for vertex in final.data.vertices)
        before = abs(mesh_volume(rest_points, triangulate_faces(faces)))
        after = abs(mesh_volume(final_points, triangulate_faces(faces)))
        relative = abs(after - before) / before
        drop = sum(point[2] for point in rest_points) / len(rest_points) - sum(point[2] for point in final_points) / len(final_points)
        self.assertLess(relative, 5.0e-5)
        self.assertGreater(drop, 0.0)

    def test_attachment_feather_adds_weighted_soft_ring(self):
        tissue = _create_grid_tissue("POUCH")
        row = next(item for item in tissue.attachments if item.mask_attribute == "BOUNDARY")
        before = len(json.loads(row.bindings_json)["bindings"])
        row.feather = 0.4
        _sync_tissue(tissue, True)
        bindings = json.loads(row.bindings_json)["bindings"]
        soft = [item for item in bindings if item["mode"] == "SOFT"]
        self.assertGreater(len(bindings), before)
        self.assertTrue(soft)
        self.assertTrue(all(0.0 < item["influence"] < 1.0 for item in soft))

    def test_surface_slack_changes_static_rest_distribution(self):
        tissue = _create_grid_tissue("POUCH")
        taut = tuple(tuple(vertex.co) for vertex in _proxy(tissue.id).data.vertices)
        tissue.surface_slack = 0.6
        _sync_tissue(tissue)
        slack = tuple(tuple(vertex.co) for vertex in _proxy(tissue.id).data.vertices)
        delta = max((Vector(a) - Vector(b)).length for a, b in zip(taut, slack))
        self.assertGreater(delta, 1.0e-3)

    def test_topology_change_keeps_last_valid_proxy(self):
        host, _scp, _base, tissue = _create_surface_tissue()
        proxy = _proxy(tissue.id)
        before = tuple(tuple(vertex.co) for vertex in proxy.data.vertices)
        host.data.vertices.add(1)
        host.data.update()
        from core.visualization.soft_tissue_sync import register_soft_tissue_sync
        register_soft_tissue_sync().sync_root_to_scene(root(), bpy.context.scene, {tissue.id})
        self.assertEqual(tuple(tuple(vertex.co) for vertex in proxy.data.vertices), before)
        self.assertEqual(soft_tissue_status(tissue), "ERROR")
        bpy.ops.af.rebind_soft_tissue()
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_manual_mode_waits_for_explicit_recompute(self):
        tissue = _create_point_tissue()
        tissue.auto_recompute = False
        tissue.inflation_amount = 0.35
        self.assertEqual(soft_tissue_status(tissue), "DIRTY")
        bpy.ops.af.recompute_soft_tissue()
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_duplicate_final_mesh_is_ordinary_object(self):
        tissue = _create_point_tissue()
        bpy.ops.af.duplicate_soft_tissue_snapshot()
        copy = bpy.data.objects.get(f"{tissue.name}_Final")
        self.assertIsNotNone(copy)
        self.assertFalse(any(str(key).startswith("af_") for key in copy.keys()))

    def test_missing_proxy_is_recreated_on_sync(self):
        tissue = _create_point_tissue()
        bpy.data.objects.remove(_proxy(tissue.id), do_unlink=True)
        sync_scene(root(), bpy.context.scene, dirty_hints_for("SOFT_TISSUE", {tissue.id}))
        self.assertIsNotNone(_proxy(tissue.id))

    def test_missing_base_retains_output_and_can_be_repaired(self):
        _host, _scp, base, tissue = _create_surface_tissue()
        before = tuple(tuple(vertex.co) for vertex in _proxy(tissue.id).data.vertices)
        bpy.data.objects.remove(base, do_unlink=True)
        sync_scene(root(), bpy.context.scene, dirty_hints_for("SOFT_TISSUE", {tissue.id}))
        self.assertEqual((soft_tissue_status(tissue), tuple(tuple(v.co) for v in _proxy(tissue.id).data.vertices)), ("ERROR", before))
        tissue.base_object_ref = _quad("Replacement Base", 0.0)
        bpy.ops.af.rebind_soft_tissue()
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_deletion_respects_base_ownership(self):
        point = _create_point_tissue()
        owned_name = point.base_object_ref.name
        self.assertTrue(delete_vcp_in_tree(bpy.context, "SOFT_TISSUE", point.id).ok)
        self.assertNotIn(owned_name, bpy.data.objects)
        self.assertEqual(root().af_vcp_system.active_vcp_type, "NONE")
        _host, _scp, base, surface = _create_surface_tissue()
        self.assertTrue(delete_vcp_in_tree(bpy.context, "SOFT_TISSUE", surface.id).ok)
        self.assertIn(base.name, bpy.data.objects)
        self.assertFalse(base.get("af_soft_tissue_base"))

    def test_blob_conversion_replaces_only_after_equivalence(self):
        root()
        bpy.ops.af.add_blob_vcp()
        self.assertEqual(bpy.ops.af.convert_blob_to_soft_tissue(), {"FINISHED"})
        self.assertEqual((len(root().af_vcp_system.blobs), len(root().af_vcp_system.soft_tissues)), (0, 1))

    def test_blob_conversion_refuses_unsupported_targets_and_offcenter_control(self):
        root()
        bpy.ops.af.add_blob_vcp()
        blob = root().af_vcp_system.blobs[-1]
        for target in ("MUSCLE", "OBJECT"):
            blob.attach_target_type = target
            self.assertFalse(convert_blob_to_soft_tissue(bpy.context).ok)
        blob.attach_target_type, blob.control_point_world = "NONE", (0.01, 0.0, 0.0)
        self.assertFalse(convert_blob_to_soft_tissue(bpy.context).ok)
        self.assertEqual((len(root().af_vcp_system.blobs), len(root().af_vcp_system.soft_tissues)), (1, 0))

    def test_blob_conversion_rolls_back_failed_equivalence(self):
        root()
        bpy.ops.af.add_blob_vcp()
        with patch("anthroforge.app.use_cases.soft_tissue_convert._validate_candidate", side_effect=ValueError("forced")):
            self.assertFalse(convert_blob_to_soft_tissue(bpy.context).ok)
        self.assertEqual((len(root().af_vcp_system.blobs), len(root().af_vcp_system.soft_tissues)), (1, 0))

    def test_two_lip_rims_preserve_both_curve_bases(self):
        host = _quad("Face Host", 0.0)
        scp_with_object(root(), "Face", host)
        curves = [_curve("Upper Lip", 0.12), _curve("Lower Lip", -0.12)]
        for curve in curves:
            _create_rim(curve, host)
        self.assertEqual(len(root().af_vcp_system.soft_tissues), 2)
        self.assertTrue(all(curve.name in bpy.context.scene.objects for curve in curves))
        self.assertTrue(all(item.base_resolution == 33 for item in root().af_vcp_system.soft_tissues))

    def test_one_owner_per_source_is_enforced_before_mutation(self):
        host = _quad("Owner Host", 0.0)
        scp_with_object(root(), "Owner Host", host)
        curve = _curve("Owned Curve", 0.0)
        _create_rim(curve, host)
        scene = bpy.context.scene
        scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = curve, host
        self.assertFalse(create_soft_tissue_vcp(bpy.context).ok)
        self.assertEqual(len(root().af_vcp_system.soft_tissues), 1)

    def test_degenerate_curve_is_rejected_before_mutation(self):
        host = _quad("Degenerate Host", 0.0)
        scp_with_object(root(), "Degenerate Host", host)
        curve = _typed_curve("Degenerate", "POLY")
        for point in curve.data.splines[0].points:
            point.co = (0.0, 0.0, 0.0, 1.0)
        scene = bpy.context.scene
        scene.af_new_soft_tissue_preset = "RIM"
        scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = curve, host
        self.assertFalse(create_soft_tissue_vcp(bpy.context).ok)
        self.assertEqual(len(root().af_vcp_system.soft_tissues), 0)

    def test_custom_preset_infers_compatible_curve_construction(self):
        root()
        curve = _curve("Custom Curve", 0.0)
        scene = bpy.context.scene
        scene.af_new_soft_tissue_preset, scene.af_new_soft_tissue_base_obj = "CUSTOM", curve
        self.assertTrue(create_soft_tissue_vcp(bpy.context).ok)
        tissue = root().af_vcp_system.soft_tissues[-1]
        self.assertEqual((tissue.base_domain, tissue.inflation_mode, soft_tissue_status(tissue)),
                         ("CURVE", "PROFILE", "CLEAN"))

    def test_supported_curve_splines_sample_exactly_and_cyclic_has_no_caps(self):
        host = _quad("Curve Host", 0.0)
        scp_with_object(root(), "Curve Host", host)
        curves = [_typed_curve("Bezier", "BEZIER"), _typed_curve("Nurbs", "NURBS"), _typed_curve("Cyclic", "POLY", True)]
        for curve in curves:
            _create_rim(curve, host)
        bindings = [json.loads(item.base_bindings_json)["bindings"] for item in root().af_vcp_system.soft_tissues]
        self.assertEqual([len(values) for values in bindings], [33, 33, 33])
        cyclic = root().af_vcp_system.soft_tissues[-1]
        self.assertEqual(len(_proxy(cyclic.id).data.polygons), 33 * cyclic.profile_segments)

    def test_bezier_handles_follow_host_frame_without_collapsing(self):
        host = _quad("Bezier Host", 0.0)
        scp = scp_with_object(root(), "Bezier Host", host)
        curve = _typed_curve("Bezier Base", "BEZIER")
        _create_rim(curve, host)
        control = curve.data.splines[0].bezier_points[0]
        before = curve.matrix_world.to_3x3() @ (control.handle_right - control.co)
        host.rotation_euler.x = 0.35
        sync_scene(root(), bpy.context.scene, dirty_hints_for("SCP", {scp.id}))
        after = curve.matrix_world.to_3x3() @ (control.handle_right - control.co)
        self.assertAlmostEqual(after.length, before.length, places=5)
        self.assertGreater((after - before).length, 1.0e-3)

    def test_mirror_and_draft_skin_include_tissue_once_per_role(self):
        _host, scp, _base, tissue = _create_surface_tissue()
        scp.mirror_enabled = True
        from core.deps.mirror_roles import apply_scp_mirror_roles
        from core.visualization.vcp_mirror_runtime import sync_vcp_mirrors
        from adapters.draft_skin.capture import capture_skin
        apply_scp_mirror_roles(root())
        sync_vcp_mirrors(root(), bpy.context.scene)
        mirrors = [obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_mirror_proxy")]
        capture = capture_skin(root(), bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        sources = [item for item in capture.sources if item.entity_type == "SOFT_TISSUE"]
        self.assertEqual((len(mirrors), len(sources), {item.mirror_role for item in sources}),
                         (1, 2, {"ORIGINAL", "MIRROR"}))


def _create_point_tissue():
    root()
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = "CLOSED_BULK"
    result = bpy.ops.af.add_soft_tissue_vcp()
    if result != {"FINISHED"}:
        raise AssertionError(result)
    return root().af_vcp_system.soft_tissues[-1]


def _create_surface_tissue():
    host = _quad("Host", 0.0)
    scp = scp_with_object(root(), "Host SCP", host)
    base = _quad("Base", 0.0)
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = "LAYER"
    scene.af_new_soft_tissue_base_obj = base
    scene.af_new_soft_tissue_host_obj = host
    if bpy.ops.af.add_soft_tissue_vcp() != {"FINISHED"}:
        raise AssertionError("Surface creation failed")
    return host, scp, base, root().af_vcp_system.soft_tissues[-1]


def _create_grid_tissue(preset):
    host = _quad(f"{preset} Host", 0.0)
    scp_with_object(root(), f"{preset} Host", host)
    base = _grid(f"{preset} Base", 7)
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = preset
    scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
    if bpy.ops.af.add_soft_tissue_vcp() != {"FINISHED"}:
        raise AssertionError(f"{preset} creation failed")
    return root().af_vcp_system.soft_tissues[-1]


def _quad(name, z):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(((-1, -1, z), (1, -1, z), (1, 1, z), (-1, 1, z)), (), ((0, 1, 2, 3),))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _x_quad(name):
    points = ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1))
    return _mesh(name, points, ((0, 1, 2, 3),))


def _cube(name):
    points = tuple((x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1))
    faces = ((0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
             (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6))
    return _mesh(name, points, faces)


def _mesh(name, points, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, (), faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _grid(name, size):
    points = [(-0.8 + 1.6 * x / (size - 1), -0.8 + 1.6 * y / (size - 1), 0.0)
              for y in range(size) for x in range(size)]
    faces = [(y * size + x, y * size + x + 1, (y + 1) * size + x + 1, (y + 1) * size + x)
             for y in range(size - 1) for x in range(size - 1)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, (), faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _curve(name, y):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new("POLY")
    spline.points.add(2)
    for point, co in zip(spline.points, ((-0.5, y, 0, 1), (0, y + 0.08, 0, 1), (0.5, y, 0, 1))):
        point.co = co
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _typed_curve(name, kind, cyclic=False):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new(kind)
    _set_curve_controls(spline, kind)
    spline.use_cyclic_u = bool(cyclic)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _set_curve_controls(spline, kind):
    if kind == "BEZIER":
        spline.bezier_points.add(2)
        for point, co in zip(spline.bezier_points, ((-0.5, 0, 0), (0, 0.15, 0), (0.5, 0, 0))):
            point.co, point.handle_left_type, point.handle_right_type = co, "AUTO", "AUTO"
        return
    spline.points.add(2)
    for point, co in zip(spline.points, ((-0.5, 0, 0, 1), (0, 0.15, 0, 1), (0.5, 0, 0, 1))):
        point.co = co


def _create_rim(curve, host):
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = "RIM"
    scene.af_new_soft_tissue_base_obj = curve
    scene.af_new_soft_tissue_host_obj = host
    if bpy.ops.af.add_soft_tissue_vcp() != {"FINISHED"}:
        raise AssertionError("Rim creation failed")


def _proxy(tissue_id):
    return next((obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_proxy")
                 and obj.get("af_soft_tissue_id") == tissue_id), None)


def _centroid_x(obj):
    return sum((obj.matrix_world @ vertex.co).x for vertex in obj.data.vertices) / len(obj.data.vertices)


def _solve_with_sagginess(tissue, value):
    from core.visualization.soft_tissue_sync import register_soft_tissue_sync
    tissue.sagginess = float(value)
    register_soft_tissue_sync().sync_root_to_scene(root(), bpy.context.scene, {tissue.id}, force=True)
    return tuple(tuple(vertex.co) for vertex in _proxy(tissue.id).data.vertices)


def _sync_tissue(tissue, recapture=False):
    from core.visualization.soft_tissue_sync import register_soft_tissue_sync
    values = {tissue.id}
    register_soft_tissue_sync().sync_root_to_scene(root(), bpy.context.scene, values,
                                                   values if recapture else set(), True)


def _surface_constraint_data(tissue):
    from core.visualization.soft_tissue_build import _fixed_indices, build_rest_shape
    from core.visualization.soft_tissue_source import sample_base
    shape = build_rest_shape(tissue, sample_base(tissue.base_object_ref, tissue, scene=bpy.context.scene))
    count = len(shape.groups.get("BACKING", ()))
    edges = {tuple(sorted((face[index], face[(index + 1) % len(face)])))
             for face in shape.faces for index in range(len(face))
             if face[index] < count and face[(index + 1) % len(face)] < count}
    return set(_fixed_indices(tissue, shape)), count, edges


def _first_free_band(fixed, count, edges):
    front_fixed = fixed & set(range(count))
    return {second for first, second in edges if first in front_fixed and second not in fixed} | {
            first for first, second in edges if second in front_fixed and first not in fixed}


def _rest_proxy(tissue_id):
    return next((obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_rest_proxy")
                 and obj.get("af_soft_tissue_id") == tissue_id), None)


if __name__ == "__main__":
    unittest.main()
