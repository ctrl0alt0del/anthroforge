import math
from unittest.mock import patch
import bpy
from mathutils import Matrix, Vector
from _helpers import BlenderTestCase, root
from test_soft_tissue_workflows import _create_grid_tissue, _create_point_tissue, _proxy, _rest_proxy, _sync_tissue, _cube
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.runtime_state import soft_tissue_status, soft_tissue_diagnostic
from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync
from anthroforge.core.visualization.soft_tissue_source import _curve_world_points
from anthroforge.app.use_cases.soft_tissue_tools import recompute_soft_tissue


def points(tissue):
    return tuple(tuple(v.co) for v in _proxy(tissue.id).data.vertices)


def configure(tissue, **values):
    with suppress_vcp_prop_updates():
        for key, value in values.items():
            setattr(tissue, key, value)


def one_attachment(tissue, mode, mask="ALL", strength=1.0, offset=0.0):
    with suppress_vcp_prop_updates():
        tissue.attachments.clear()
        row = tissue.attachments.add()
        row.mode, row.mask_attribute, row.strength, row.normal_offset = mode, mask, strength, offset
    _sync_tissue(tissue, True)
    return row


def nurbs():
    data = bpy.data.curves.new("Regression NURBS", "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new("NURBS")
    spline.points.add(2)
    for point, co in zip(spline.points, ((-.3, 0, 0, 1), (0, .15, 0, 1), (.3, 0, 0, 1))):
        point.co = co
    spline.order_u, spline.use_endpoint_u = 3, True
    obj = bpy.data.objects.new(data.name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


class TissueRepairTests(BlenderTestCase):
    def test_native_point_matches_legacy_blob_on_transformed_host(self):
        from anthroforge.core.visualization.soft_tissue_build import build_rest_shape, _blob_runtime, _geometric_point
        from anthroforge.core.visualization.soft_tissue_source import sample_base
        from anthroforge.core.vcp.blob_solver import BlobSolver
        tissue, host = _create_point_tissue(), _cube("Point host")
        host.scale, host.rotation_euler.y = (1.1, .7, 1.3), .2
        bpy.context.view_layer.update()
        rest = build_rest_shape(tissue, sample_base(tissue.base_object_ref, tissue))
        expected = BlobSolver().solve(_blob_runtime(tissue), host, [Vector(p) for p in rest.vertices], rest.faces)
        actual = _geometric_point(tissue, rest, host)
        self.assertLess(max((Vector(a)-b).length for a, b in zip(actual.vertices, expected.points)), 2.e-6)

    def test_first_target_rotation_uses_resolved_base_normals(self):
        tissue = _create_grid_tissue("LAYER")
        configure(tissue, relaxation_mode="NONE")
        _sync_tissue(tissue)
        before = points(tissue)
        host = next(s.geometry_object_ref for s in root().af_scp_system.scps if s.id == tissue.attachment_target_id)
        rotation = Matrix.Rotation(math.pi/2, 4, "Y")
        host.matrix_world = rotation
        bpy.context.view_layer.update()
        _sync_tissue(tissue)
        self.assertLess(max((Vector(a)-rotation@Vector(b)).length for a, b in zip(points(tissue), before)), 2.e-6)
        once = points(tissue)
        _sync_tissue(tissue)
        self.assertEqual(once, points(tissue))

    def test_nurbs_uses_evaluated_centerline_and_cleans_temporary_data(self):
        obj = nurbs()
        obj.data.bevel_depth = .04
        before = (len(bpy.data.objects), len(bpy.data.curves))
        sampled, cyclic = _curve_world_points(obj, 33, bpy.context.scene)
        self.assertFalse(cyclic)
        self.assertAlmostEqual(max(p[1] for p in sampled), .075, delta=2.e-4)
        self.assertEqual(before, (len(bpy.data.objects), len(bpy.data.curves)))
        self.assertAlmostEqual(obj.data.bevel_depth, .04)

    def test_explicit_zero_field_is_preserved(self):
        tissue = _create_grid_tissue("LAYER")
        self.assertIsNone(tissue.base_object_ref.vertex_groups.get(tissue.field_attribute))
        tissue.base_object_ref.vertex_groups.new(name=tissue.field_attribute)
        _sync_tissue(tissue, True)
        rest = _rest_proxy(tissue.id).data.vertices
        count = len(rest)//2
        self.assertLess(max(abs((rest[i].co-rest[i+count].co).length-tissue.minimum_amount) for i in range(count)), 1.e-6)

    def test_nurbs_respects_weights_order_and_cyclic_sampling(self):
        obj = nurbs()
        spline = obj.data.splines[0]
        spline.points[1].co.w = 2
        sampled, _ = _curve_world_points(obj, 33, bpy.context.scene)
        self.assertAlmostEqual(max(p[1] for p in sampled), .1, delta=3.e-4)
        spline.order_u = 2
        sampled, _ = _curve_world_points(obj, 33, bpy.context.scene)
        self.assertAlmostEqual(max(p[1] for p in sampled), .15, delta=3.e-4)
        spline.use_cyclic_u = True
        sampled, cyclic = _curve_world_points(obj, 33, bpy.context.scene)
        self.assertTrue(cyclic)
        self.assertEqual(len(sampled), 33)
        self.assertGreater((Vector(sampled[0])-Vector(sampled[-1])).length, 1.e-4)

    def test_fixed_offset_changes_geometric_and_static_front_goals(self):
        tissue = _create_grid_tissue("LAYER")
        row = one_attachment(tissue, "FIXED", "BOUNDARY")
        before = points(tissue)
        configure(row, normal_offset=.04)
        _sync_tissue(tissue)
        self.assertAlmostEqual(points(tissue)[0][2]-before[0][2], .04, places=6)
        configure(tissue, relaxation_mode="STATIC_PBD")
        _sync_tissue(tissue)
        self.assertAlmostEqual(points(tissue)[0][2]-before[0][2], .04, places=6)

    def test_painted_soft_weight_is_continuous(self):
        tissue = _create_grid_tissue("LAYER")
        configure(tissue, sagginess=0)
        group = tissue.base_object_ref.vertex_groups.new(name="Quarter")
        group.add(list(range(49)), .25, "REPLACE")
        row = one_attachment(tissue, "SOFT", "Quarter", offset=.08)
        rest = _rest_proxy(tissue.id).data.vertices
        self.assertAlmostEqual(points(tissue)[24][2]-rest[24].co.z, .02, places=6)
        configure(row, strength=0)
        _sync_tissue(tissue)
        self.assertAlmostEqual(points(tissue)[24][2]-rest[24].co.z, 0, places=6)

    def test_forced_auto_sync_does_not_upgrade_legacy(self):
        tissue = _create_grid_tissue("LAYER")
        before = points(tissue)
        configure(tissue, evaluation_revision=0, inflation_amount=.5)
        _sync_tissue(tissue)
        self.assertEqual(points(tissue), before)
        self.assertEqual(tissue.evaluation_revision, 0)
        self.assertIn("Upgrade required", soft_tissue_diagnostic(tissue)[3])
        self.assertTrue(recompute_soft_tissue(bpy.context).ok)
        self.assertEqual(tissue.evaluation_revision, 1)
        self.assertNotEqual(points(tissue), before)

    def test_failed_publication_restores_cache_and_bindings(self):
        tissue = _create_grid_tissue("LAYER")
        before, bindings = points(tissue), tissue.base_bindings_json
        configure(tissue, inflation_amount=.6)
        with patch("core.visualization.soft_tissue_sync._commit_evaluation", side_effect=ValueError("injected commit failure")):
            _sync_tissue(tissue, True)
        self.assertEqual(soft_tissue_status(tissue), "ERROR")
        self.assertEqual(points(tissue), before)
        self.assertEqual(tissue.base_bindings_json, bindings)

    def test_missing_base_recompute_returns_failure(self):
        tissue = _create_grid_tissue("LAYER")
        configure(tissue, base_object_ref=None)
        self.assertFalse(recompute_soft_tissue(bpy.context).ok)

    def test_attachment_rows_add_remove_and_validate_masks(self):
        tissue = _create_grid_tissue("LAYER")
        count = len(tissue.attachments)
        self.assertEqual(bpy.ops.af.add_soft_tissue_attachment(), {"FINISHED"})
        self.assertEqual(len(tissue.attachments), count+1)
        self.assertEqual(bpy.ops.af.select_soft_tissue_attachment_mask(index=count, mask="BOUNDARY"), {"FINISHED"})
        self.assertEqual(tissue.attachments[count].mask_attribute, "BOUNDARY")
        self.assertEqual(bpy.ops.af.remove_soft_tissue_attachment(index=count), {"FINISHED"})
        configure(tissue.attachments[0], mask_attribute="Missing Mask")
        _sync_tissue(tissue, True)
        self.assertEqual(soft_tissue_status(tissue), "ERROR")

    def test_conflicting_fixed_goals_retain_last_valid_output(self):
        tissue = _create_grid_tissue("LAYER")
        one_attachment(tissue, "FIXED", "ALL")
        before = points(tissue)
        with suppress_vcp_prop_updates():
            row = tissue.attachments.add()
            row.mode, row.mask_attribute, row.normal_offset = "FIXED", "ALL", .1
        _sync_tissue(tissue, True)
        self.assertEqual(soft_tissue_status(tissue), "ERROR")
        self.assertIn("Conflicting", soft_tissue_diagnostic(tissue)[3])
        self.assertEqual(points(tissue), before)
