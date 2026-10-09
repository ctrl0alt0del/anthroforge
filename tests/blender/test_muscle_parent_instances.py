"""Mirrored geometry must follow the actual parent surface through consumers."""
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, find_flagged
from test_muscle_parent_fibers import tissue_chain, mirrored_surface
from anthroforge.core.visualization.vcp_mirror_runtime import sync_vcp_mirrors
from anthroforge.core.visualization.muscle_sync import register_muscle_sync


def fixture():
    owner, muscle, tissue, surface = tissue_chain('LAYER')
    mirrored_surface(owner, muscle, surface)
    children = [f for f in owner.af_vcp_system.fibers if f.behavior_mode == 'FREE']
    for fiber in children:
        fiber['af_authoring_symmetry'] = 'native_mirror'
        fiber['af_authoring_mirror_axis'] = 'X'; fiber['af_authoring_mirror_origin'] = [0., 0., 0.]
    sync_vcp_mirrors(owner, bpy.context.scene, {f.id for f in children}, (), (), ())
    from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync
    register_fiber_surface_sync().sync_root_to_scene(owner, bpy.context.scene, {tissue.base_source_id})
    from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync
    register_soft_tissue_sync().sync_root_to_scene(owner, bpy.context.scene, {tissue.id}, force=True)
    return owner, tissue, children


def mirror(scene, kind, identity):
    return next(o for o in scene.objects if o.get('af_' + kind + '_mirror_proxy')
                and o.get('af_source_' + kind + '_id') == identity)


def assert_displacement(test, source, output):
    test.assertEqual(len(source.data.vertices), len(output.data.vertices))
    errors = []
    for a, b in zip(source.data.vertices, output.data.vertices):
        expected = source.matrix_world @ a.co
        expected.x = -expected.x; expected.z += .25
        errors.append((output.matrix_world @ b.co - expected).length)
    test.assertLess(max(errors), 3e-5, (output.name, max(errors)))


def assert_reflected_ridge(test, source, output, width):
    # Reflection reverses the lateral ring order to retain outward face winding.
    points = source.rest.vertices
    expected = [p for i in range(0, len(points), width) for p in reversed(points[i:i+width])]
    for a, b in zip(expected, output.rest.vertices):
        test.assertLess((Vector((a[0],a[1],-a[2]))-Vector(b)).length, 1e-5)


class MuscleParentInstanceTests(BlenderTestCase):
    def test_z_mirrored_rim_preserves_curve_frame_orientation(self):
        from _helpers import select_only
        from anthroforge.core.visualization.geometry_instance import mirrored
        from test_muscle_parent_acceptance import tissue_result
        owner, _layer, children = fixture(); fiber = children[0]
        select_only(find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id'))
        bpy.context.scene.af_new_soft_tissue_preset = 'RIM'
        self.assertEqual(bpy.ops.af.add_soft_tissue_vcp(), {'FINISHED'})
        tissue = owner.af_vcp_system.soft_tissues[-1]; source = tissue_result(owner, tissue)
        from unittest.mock import patch
        reflected = [Vector((x,y,-z)) for x,y,z in source.sample.points]
        with patch('anthroforge.core.visualization.fiber_instance_runtime.actual_rows', return_value=reflected), mirrored(('Z',(0,0,0))):
            output = tissue_result(owner, tissue)
        assert_reflected_ridge(self, source, output, tissue.profile_segments)

    def test_independent_mirror_exports_its_own_stacking_constraints(self):
        from _helpers import select_only
        from anthroforge.core.muscle_pairs.capture import capture_muscle
        from anthroforge.core.muscle_pairs.model import DetectionSettings
        owner, tissue, _children = fixture()
        select_only(find_flagged('af_fiber_surface_proxy', tissue.base_source_id, 'af_fiber_surface_id'))
        self.assertEqual(bpy.ops.af.create_muscle_from_fiber_surface(surface_id=tissue.base_source_id), {'FINISHED'})
        muscle = owner.af_vcp_system.muscles[-1]; muscle.inflation_mode = 'DISTRIBUTED'
        register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, target_muscle_ids={muscle.id})
        sync_vcp_mirrors(owner, bpy.context.scene, (), {muscle.id}, (), ())
        domains = capture_muscle(owner, bpy.context.scene, muscle, DetectionSettings(), tuple(bpy.context.scene.objects))
        self.assertEqual({d.key.instance for d in domains}, {'source', 'mirror'})
        self.assertTrue(all(d.material.constraints and len(d.material.fixed) for d in domains))

    def test_free_loft_and_layer_use_asymmetric_mirror(self):
        owner, tissue, children = fixture()
        for fiber in children:
            self.assertEqual(mirror(bpy.context.scene, 'fiber', fiber.id).get('af_fiber_output_state'), 'CURRENT')
        source = find_flagged('af_fiber_surface_proxy', tissue.base_source_id, 'af_fiber_surface_id')
        loft = mirror(bpy.context.scene, 'fiber_surface', tissue.base_source_id)
        self.assertEqual(loft.get('af_fiber_surface_output_state'), 'CURRENT', loft.get('af_attachment_error'))
        assert_displacement(self, source, loft)
        sync_vcp_mirrors(owner, bpy.context.scene, (), (), (), {tissue.id})
        output = mirror(bpy.context.scene, 'soft_tissue', tissue.id)
        self.assertEqual(output.get('af_soft_tissue_output_state'), 'CURRENT', output.get('af_attachment_error'))
        source = find_flagged('af_soft_tissue_proxy', tissue.id, 'af_soft_tissue_id')
        assert_displacement(self, source, output)

    def test_nested_muscle_uses_actual_mirror_rows(self):
        from _helpers import select_only
        owner, tissue, _children = fixture()
        loft = find_flagged('af_fiber_surface_proxy', tissue.base_source_id, 'af_fiber_surface_id')
        select_only(loft); self.assertEqual(bpy.ops.af.create_muscle_from_fiber_surface(surface_id=tissue.base_source_id), {'FINISHED'})
        muscle = owner.af_vcp_system.muscles[-1]
        muscle.inflation_mode = 'DISTRIBUTED'
        register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, target_muscle_ids={muscle.id})
        sync_vcp_mirrors(owner, bpy.context.scene, (), {muscle.id}, (), ())
        for role in ('BASE', 'INFL'):
            source = next(o for o in bpy.context.scene.objects if o.get('af_muscle_id') == muscle.id
                          and o.get('af_muscle_surface') == role and not o.get('af_muscle_mirror_proxy'))
            output = next(o for o in bpy.context.scene.objects if o.get('af_source_muscle_id') == muscle.id
                          and o.get('af_muscle_surface') == role and o.get('af_muscle_mirror_proxy'))
            self.assertEqual(output.get('af_muscle_output_state'), 'CURRENT', output.get('af_attachment_error'))
            assert_displacement(self, source, output)
