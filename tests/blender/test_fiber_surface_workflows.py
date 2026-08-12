import json
import os

import bpy
import bmesh

from _helpers import BlenderTestCase, empty_object, find_flagged, mesh_object, reset_scene, root, scp_with_object, temp_blend_path
from anthroforge.core.importing.service import import_package_from_blend, import_vcp_from_blend
from app.runtime_api import sync_scene
from app.use_cases.vcp_delete import delete_vcp_in_tree
from core.deps.dirty_hints import dirty_hints_for
from core.deps.mirror_roles import apply_scp_mirror_roles
from core.id_utils import next_prefixed_id
from core.scp_runtime.lookup import set_parent_relation
from core.vcp.prop_update_guard import suppress_vcp_prop_updates
from core.vcp.runtime_state import fiber_surface_diagnostic, fiber_surface_status
from core.visualization.fiber_surface_sync import find_fiber_surface_proxy, register_fiber_surface_sync
from core.visualization.muscle_sync import register_muscle_sync
from core.visualization.vcp_mirror_runtime import sync_vcp_mirrors


def _open_fiber(root_obj, name, y):
    origin = scp_with_object(root_obj, f"{name}O", mesh_object(f"{name}O", (0.0, y, 0.0)))
    insertion = scp_with_object(root_obj, f"{name}I", mesh_object(f"{name}I", (2.0, y, 0.0)))
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insertion.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()
    fiber = root_obj.af_vcp_system.fibers[-1]
    return fiber, find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")


def _loop_mesh(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _edit_all_vertices(obj):
    _select([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    for vertex in bm.verts:
        vertex.select_set(True)
    bmesh.update_edit_mesh(obj.data)


def _loop_fiber(root_obj):
    loop = scp_with_object(root_obj, "Loop", _loop_mesh("Loop"))
    _edit_all_vertices(loop.geometry_object_ref)
    bpy.ops.af.create_loop_fiber_from_selected_vertices()
    fiber = root_obj.af_vcp_system.fibers[-1]
    return fiber, find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")


def _select(objects):
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[-1]


class FiberSurfaceWorkflowTests(BlenderTestCase):
    def test_loft_surface_and_muscle_are_separate_records(self):
        root_obj = root()
        first, first_obj = _open_fiber(root_obj, "A", 0.0)
        second, second_obj = _open_fiber(root_obj, "B", 1.0)
        _select([first_obj, second_obj])
        self.assertEqual(bpy.ops.af.create_fiber_surface(), {"FINISHED"})
        surface = root_obj.af_vcp_system.fiber_surfaces[0]
        proxy = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        self.assertEqual(surface.construction_mode, "LOFT")
        self.assertGreater(len(proxy.data.polygons), 0)
        self.assertEqual(bpy.ops.af.create_muscle_from_fiber_surface(surface_id=surface.id), {"FINISHED"})
        muscle = root_obj.af_vcp_system.muscles[0]
        self.assertEqual((muscle.surface_source_mode, muscle.fiber_surface_id), ("FIBER_SURFACE", surface.id))
        self.assertEqual((first.muscle_id, second.muscle_id, len(muscle.fiber_refs)), ("", "", 0))

    def test_loop_patch_preserves_existing_loop_boundary(self):
        root_obj = root()
        fiber, proxy = _loop_fiber(root_obj)
        points = json.loads(proxy["af_fiber_points_world"])
        _select([proxy])
        self.assertEqual(bpy.ops.af.create_fiber_surface(), {"FINISHED"})
        surface = root_obj.af_vcp_system.fiber_surfaces[0]
        result = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        boundary = [tuple(vertex.co) for vertex in result.data.vertices[-len(points):]]
        self.assertEqual(surface.construction_mode, "LOOP_PATCH")
        self.assertEqual([tuple(round(value, 5) for value in point) for point in boundary],
                         [tuple(round(value, 5) for value in point) for point in points])

    def test_derived_soft_tissue_uses_stable_source_id(self):
        root_obj = root()
        fiber, proxy = _open_fiber(root_obj, "A", 0.0)
        _select([proxy])
        bpy.context.scene.af_new_soft_tissue_preset = "CUSTOM"
        self.assertEqual(bpy.ops.af.add_soft_tissue_vcp(), {"FINISHED"})
        tissue = root_obj.af_vcp_system.soft_tissues[0]
        self.assertEqual((tissue.base_source_type, tissue.base_source_id, tissue.base_domain),
                         ("FIBER", fiber.id, "CURVE"))

    def test_fiber_tissue_inherits_source_mirror_rule(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Mirror", empty_object("Mirror"), with_geometry=False)
        source.mirror_enabled = True
        fiber, proxy = _open_fiber(root_obj, "A", 0.0)
        for scp in root_obj.af_scp_system.scps[1:]:
            set_parent_relation(scp.transform_object_ref, scp, source.transform_object_ref)
        _select([proxy])
        bpy.context.scene.af_new_soft_tissue_preset = "CUSTOM"
        self.assertEqual(bpy.ops.af.add_soft_tissue_vcp(), {"FINISHED"})
        apply_scp_mirror_roles(root_obj)
        sync_vcp_mirrors(root_obj, bpy.context.scene)
        mirrors = [obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_mirror_proxy")]
        self.assertEqual((len(mirrors), root_obj.af_vcp_system.soft_tissues[0].base_source_id), (1, fiber.id))

    def test_legacy_conversion_is_geometry_preserving(self):
        root_obj = root()
        first, first_obj = _open_fiber(root_obj, "A", 0.0)
        second, _second_obj = _open_fiber(root_obj, "B", 1.0)
        muscle = _legacy_muscle(root_obj, [first.id, second.id])
        register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene)
        self.assertEqual(bpy.ops.af.convert_muscle_to_fiber_surface(muscle_id=muscle.id), {"FINISHED"})
        self.assertEqual((muscle.surface_source_mode, len(root_obj.af_vcp_system.fiber_surfaces)),
                         ("FIBER_SURFACE", 1))
        self.assertEqual((len(muscle.fiber_refs), first.muscle_id, second.muscle_id), (0, "", ""))
        surface = root_obj.af_vcp_system.fiber_surfaces[0]
        register_fiber_surface_sync().sync_root_to_scene(root_obj, bpy.context.scene, {surface.id})
        self.assertIsNotNone(find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id))
        self.assertIsNotNone(first_obj)

    def test_recompute_recreates_deleted_surface_proxy(self):
        root_obj = root()
        _fiber_a, first = _open_fiber(root_obj, "A", 0.0)
        _fiber_b, second = _open_fiber(root_obj, "B", 1.0)
        _select([first, second])
        bpy.ops.af.create_fiber_surface()
        surface = root_obj.af_vcp_system.fiber_surfaces[0]
        proxy = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        bpy.data.objects.remove(proxy, do_unlink=True)
        register_fiber_surface_sync().sync_root_to_scene(root_obj, bpy.context.scene, {surface.id})
        self.assertIsNotNone(find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id))

    def test_full_package_round_trip_preserves_surface_graph(self):
        path = _surface_muscle_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        result = import_package_from_blend(path, bpy.context)
        imported = root().af_vcp_system
        refs = {ref.fiber_id for ref in imported.fiber_surfaces[0].fiber_refs}
        self.assertEqual((result.fiber_count, result.fiber_surface_count, result.muscle_count), (2, 1, 1))
        self.assertEqual((refs, imported.muscles[0].fiber_surface_id),
                         ({fiber.id for fiber in imported.fibers}, imported.fiber_surfaces[0].id))

    def test_sources_are_blocked_until_consumers_are_deleted(self):
        root_obj, surface, muscle = _surface_and_muscle()
        fiber_id = root_obj.af_vcp_system.fibers[0].id
        blocked_fiber = delete_vcp_in_tree(bpy.context, "FIBER", fiber_id)
        blocked_surface = delete_vcp_in_tree(bpy.context, "FIBER_SURFACE", surface.id)
        self.assertFalse(blocked_fiber.ok or blocked_surface.ok)
        self.assertIn(surface.id, blocked_fiber.message)
        self.assertIn(muscle.id, blocked_surface.message)
        self.assertTrue(delete_vcp_in_tree(bpy.context, "MUSCLE", muscle.id).ok)
        self.assertTrue(delete_vcp_in_tree(bpy.context, "FIBER_SURFACE", surface.id).ok)
        self.assertEqual(len(root_obj.af_vcp_system.fibers), 2)

    def test_fiber_surface_can_feed_multiple_soft_tissues(self):
        root_obj, surface = _surface_only()
        proxy = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        bpy.context.scene.af_new_soft_tissue_preset = "CUSTOM"
        for _index in range(2):
            _select([proxy])
            self.assertEqual(bpy.ops.af.add_soft_tissue_vcp(), {"FINISHED"})
        sources = {(item.base_source_type, item.base_source_id) for item in root_obj.af_vcp_system.soft_tissues}
        self.assertEqual((len(root_obj.af_vcp_system.soft_tissues), sources),
                         (2, {("FIBER_SURFACE", surface.id)}))

    def test_scp_change_propagates_through_surface(self):
        root_obj, surface = _surface_only()
        proxy = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        before = tuple(tuple(vertex.co) for vertex in proxy.data.vertices)
        target = next(item for item in root_obj.af_scp_system.scps if item.name == "BI")
        target.transform_object_ref.location.x += 0.5
        sync_scene(root_obj, bpy.context.scene, dirty_hints_for("SCP", {target.id}))
        proxy = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        after = tuple(tuple(vertex.co) for vertex in proxy.data.vertices)
        self.assertNotEqual(before, after)

    def test_vcp_import_preserves_new_source_contract(self):
        path = _surface_muscle_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        _matching_four_scps()
        result = import_vcp_from_blend(path, bpy.context)
        imported = root().af_vcp_system
        muscle = imported.muscles[0]
        self.assertEqual((result.fiber_count, result.fiber_surface_count, result.muscle_count), (2, 1, 1))
        self.assertEqual((muscle.surface_source_mode, len(muscle.fiber_refs)), ("FIBER_SURFACE", 0))
        self.assertTrue(all(not fiber.muscle_id for fiber in imported.fibers))

    def test_invalid_source_retains_last_valid_surface(self):
        root_obj, surface = _surface_only()
        proxy = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        before = tuple(tuple(vertex.co) for vertex in proxy.data.vertices)
        with suppress_vcp_prop_updates():
            surface.fiber_refs[0].fiber_id = "MISSING"
        register_fiber_surface_sync().sync_root_to_scene(root_obj, bpy.context.scene, {surface.id})
        after = tuple(tuple(vertex.co) for vertex in proxy.data.vertices)
        self.assertEqual((before, fiber_surface_status(surface)), (after, "ERROR"))
        self.assertIn("missing", fiber_surface_diagnostic(surface)[1].lower())

    def test_conversion_mismatch_rolls_back_candidate(self):
        root_obj = root()
        first, _first_obj = _open_fiber(root_obj, "A", 0.0)
        second, _second_obj = _open_fiber(root_obj, "B", 1.0)
        muscle = _legacy_muscle(root_obj, [first.id, second.id])
        register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene)
        base = find_flagged("af_muscle_proxy", muscle.id, "af_muscle_id")
        base.data.vertices[0].co.x += 0.25
        with self.assertRaises(RuntimeError):
            bpy.ops.af.convert_muscle_to_fiber_surface(muscle_id=muscle.id)
        self.assertEqual((muscle.surface_source_mode, len(root_obj.af_vcp_system.fiber_surfaces)),
                         ("LEGACY_FIBERS", 0))


def _legacy_muscle(root_obj, fiber_ids):
    muscle = root_obj.af_vcp_system.muscles.add()
    muscle.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    muscle.name = muscle.id
    for fiber_id in fiber_ids:
        muscle.fiber_refs.add().fiber_id = fiber_id
        next(fiber for fiber in root_obj.af_vcp_system.fibers if fiber.id == fiber_id).muscle_id = muscle.id
    root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "MUSCLE", muscle.id
    return muscle


def _surface_muscle_file():
    _root_obj, _surface, _muscle = _surface_and_muscle()
    path = temp_blend_path()
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path


def _surface_and_muscle():
    root_obj, surface = _surface_only()
    bpy.ops.af.create_muscle_from_fiber_surface(surface_id=surface.id)
    return root_obj, surface, root_obj.af_vcp_system.muscles[0]


def _surface_only():
    root_obj = root()
    _first, first = _open_fiber(root_obj, "A", 0.0)
    _second, second = _open_fiber(root_obj, "B", 1.0)
    _select([first, second])
    bpy.ops.af.create_fiber_surface()
    surface = root_obj.af_vcp_system.fiber_surfaces[0]
    return root_obj, surface


def _matching_four_scps():
    root_obj = root()
    items = (("AO", (0.0, 0.0, 0.0)), ("AI", (2.0, 0.0, 0.0)),
             ("BO", (0.0, 1.0, 0.0)), ("BI", (2.0, 1.0, 0.0)))
    for name, location in items:
        scp_with_object(root_obj, name, mesh_object(name, location))
