"""Real Blender persistence and dependency updates for muscle-attached Free chains."""
from pathlib import Path
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, temp_blend_path, reset_scene, root, find_flagged
from test_muscle_parent_fibers import tissue_chain
from anthroforge.core.vcp.surface_reference import reference
from anthroforge.core.visualization.free_fiber_runtime import current


def saved(test):
    owner, muscle, tissue, surface = tissue_chain('LAYER')
    fibers = tuple(f for f in owner.af_vcp_system.fibers if f.behavior_mode == 'FREE')
    raw = tuple(f.node_attachments_json for f in fibers)
    points = tuple(tuple(tuple(p) for p in current(owner, bpy.context.scene, f)[1]) for f in fibers)
    path = temp_blend_path(); test.addCleanup(lambda: Path(path).unlink(missing_ok=True))
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path, raw, points


class MuscleParentPersistenceTests(BlenderTestCase):
    def test_save_reopen_preserves_pairing_and_world_geometry(self):
        path, raw, before = saved(self)
        bpy.ops.wm.open_mainfile(filepath=path)
        fibers = tuple(f for f in root().af_vcp_system.fibers if f.behavior_mode == 'FREE')
        self.assertEqual(raw, tuple(f.node_attachments_json for f in fibers))
        for fiber, expected in zip(fibers, before):
            values = current(root(), bpy.context.scene, fiber)[1]
            self.assertLess(max((p - Vector(q)).length for p, q in zip(values, expected)), 1e-5)

    def test_package_remaps_parent_and_recreates_chain(self):
        from anthroforge.core.importing.service import import_package_from_blend
        path, _raw, _points = saved(self); reset_scene()
        result = import_package_from_blend(path, bpy.context)
        owner = root(); fibers = [f for f in owner.af_vcp_system.fibers if f.behavior_mode == 'FREE']
        self.assertEqual(len(fibers), 2)
        for fiber in fibers:
            self.assertIn(reference(fiber.a_parent_id).entity_id, {m.id for m in owner.af_vcp_system.muscles})
            self.assertTrue(current(owner, bpy.context.scene, fiber)[1])
        tissue = owner.af_vcp_system.soft_tissues[-1]
        self.assertEqual(tissue.constraint_reference, 'SOURCE')
        proxy = find_flagged('af_soft_tissue_proxy', tissue.id, 'af_soft_tissue_id')
        self.assertTrue(proxy and len(proxy.data.vertices))

    def test_parent_inflation_propagates_complete_chain(self):
        from anthroforge.core.visualization.sync_runner import sync_from_dirty_hints
        from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
        owner, muscle, tissue, surface = tissue_chain('LAYER')
        proxy = find_flagged('af_soft_tissue_proxy', tissue.id, 'af_soft_tissue_id')
        before = tuple(v.co.copy() for v in proxy.data.vertices)
        with suppress_vcp_prop_updates(): muscle.inflation_max_value += .05
        sync_from_dirty_hints(owner, bpy.context.scene, {'MUSCLE': {muscle.id}}, source='test', event_type='UPDATE')
        self.assertTrue(any((v.co - p).length > 1e-4 for v, p in zip(proxy.data.vertices, before)))
        self.assertEqual(proxy.get('af_soft_tissue_output_state'), 'CURRENT')
