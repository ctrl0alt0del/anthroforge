"""AF-11: authored placement and complete surfaces survive ordinary reloads."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import bpy
import numpy as np
from mathutils import Vector

from _helpers import BlenderTestCase, find_flagged, mesh_object, root, scp_with_object
from test_muscle_vcp_workflows import _add_fiber, _muscle_setup, _new_muscle, _surface_obj
from anthroforge.core.vcp.muscle_inflation_state import (INITIALIZED_KEY, LEGACY_KEY,
    WORLD_KEY, inflation_control_initialized, inflation_control_world, migrate_inflation_control,
    set_inflation_control_world)
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.muscle_numeric import MuscleNumericBatchResult, _invalid_result
from anthroforge.core.visualization.muscle_sync import apply_muscle_control_update, register_muscle_sync
from anthroforge.core.visualization.muscle_numeric_runtime import _numeric_input


def _sync(root_obj):
    register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene)


def _setup():
    root_obj, _first, _second = _muscle_setup()
    for index in (3, 4):
        start = scp_with_object(root_obj, f"A{index}", mesh_object(f"A{index}", (0, index, 0)))
        end = scp_with_object(root_obj, f"B{index}", mesh_object(f"B{index}", (2, index, 0)))
        _add_fiber(start, end)
    ids = [fiber.id for fiber in root_obj.af_vcp_system.fibers]
    with suppress_vcp_prop_updates():
        for pair in (ids[:2], ids[2:]):
            muscle = _new_muscle(root_obj, pair)
            muscle.inflation_max_value, muscle.inflation_falloff_radius = 0.3, 1.5
    _sync(root_obj)
    return root_obj


def _author(root_obj, origin=False):
    for muscle in root_obj.af_vcp_system.muscles:
        grid = _numeric_input(register_muscle_sync(), root_obj, bpy.context.scene, muscle)[0]
        point = np.asarray(grid[len(grid) // 2][3 * len(grid[0]) // 4]) + (0, 0, 0.031)
        set_inflation_control_world(muscle, (0, 0, 0) if origin else point)
    _sync(root_obj)


def _select(root_obj, selected):
    vcp = root_obj.af_vcp_system
    kind, key = ("MUSCLE", vcp.muscles[0].id) if selected else ("FIBER", vcp.fibers[0].id)
    assert bpy.ops.af.select_vcp_in_tree(node_type=kind, node_id=key) == {"FINISHED"}
    _sync(root_obj)


def _mesh_state(root_obj, muscle, surface):
    obj = _surface_obj(root_obj, muscle, surface)
    return (np.asarray([tuple(vertex.co) for vertex in obj.data.vertices]),
            tuple(tuple(face.vertices) for face in obj.data.polygons))


def _state(root_obj):
    return {muscle.id: (inflation_control_world(muscle), inflation_control_initialized(muscle),
                       _mesh_state(root_obj, muscle, "BASE"), _mesh_state(root_obj, muscle, "INFL"))
            for muscle in root_obj.af_vcp_system.muscles}


def _assert_state(test, expected, actual):
    test.assertEqual(expected.keys(), actual.keys())
    for key, before in expected.items():
        after = actual[key]
        np.testing.assert_allclose(after[0], before[0], atol=1e-7, rtol=0)
        test.assertEqual(after[1], before[1])
        for slot, tolerance in ((2, 1e-7), (3, 1e-6)):
            test.assertGreater(len(before[slot][0]), 0)
            np.testing.assert_allclose(after[slot][0], before[slot][0], atol=tolerance, rtol=0)
            test.assertEqual(after[slot][1], before[slot][1])


def _reload_cycles(test, baseline, cycles=3):
    with TemporaryDirectory(prefix="af11-reload-") as directory:
        path = str(Path(directory) / "muscles.blend")
        for cycle in range(cycles):
            with test.subTest(cycle=cycle):
                bpy.ops.wm.save_as_mainfile(filepath=path)
                bpy.ops.wm.open_mainfile(filepath=path, use_scripts=False)
                _assert_state(test, baseline, _state(root()))
                _sync(root())
                _assert_state(test, baseline, _state(root()))


def _clear_placement(muscle):
    for key in (WORLD_KEY, INITIALIZED_KEY, LEGACY_KEY):
        if key in muscle:
            del muscle[key]


def _control(muscle):
    return find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")


def _assert_midpoint(test, root_obj, muscle):
    columns = root_obj.af_vcp_system.fibers[0].node_count
    grid = _mesh_state(root_obj, muscle, "BASE")[0].reshape((-1, columns, 3))
    expected = grid[len(grid) // 2, columns // 2]
    test.assertGreater(np.linalg.norm(expected), 0.1)
    np.testing.assert_allclose(inflation_control_world(muscle), expected, atol=1e-7, rtol=0)


class MuscleInflationPersistenceTests(BlenderTestCase):
    def test_selected_offcentre_survives_three_reload_cycles(self):
        root_obj = _setup()
        _author(root_obj)
        _select(root_obj, True)
        _reload_cycles(self, _state(root_obj))

    def test_unselected_offcentre_survives_three_reload_cycles(self):
        root_obj = _setup()
        _author(root_obj)
        _select(root_obj, False)
        _reload_cycles(self, _state(root_obj))

    def test_authored_world_origin_survives_reload(self):
        root_obj = _setup()
        _author(root_obj, origin=True)
        _select(root_obj, True)
        self.assertEqual(inflation_control_world(root_obj.af_vcp_system.muscles[0]), (0, 0, 0))
        _reload_cycles(self, _state(root_obj), cycles=1)

    def test_missing_control_initializes_unselected_from_nonzero_midpoint(self):
        root_obj = _setup()
        _select(root_obj, False)
        for muscle in root_obj.af_vcp_system.muscles:
            _clear_placement(muscle)
        _sync(root_obj)
        for muscle in root_obj.af_vcp_system.muscles:
            self.assertTrue(inflation_control_initialized(muscle))
            _assert_midpoint(self, root_obj, muscle)
            self.assertIsNone(_control(muscle))

    def test_absent_invalid_input_is_not_marked_initialized(self):
        muscle = root().af_vcp_system.muscles.add()
        muscle.id = "MUSCLE_1"
        _sync(root())
        self.assertFalse(inflation_control_initialized(muscle))

    def test_failed_numeric_result_does_not_initialize_control(self):
        root_obj = _setup()
        muscles = tuple(root_obj.af_vcp_system.muscles)
        for muscle in muscles:
            _clear_placement(muscle)
        results = tuple(_invalid_result(muscle.id, "Expected backend failure") for muscle in muscles)
        batch = MuscleNumericBatchResult(results, "NATIVE", 0.0)
        with patch("anthroforge.core.visualization.muscle_numeric_runtime.execute_muscle_batch", return_value=batch):
            _sync(root_obj)
        self.assertTrue(all(not inflation_control_initialized(muscle) for muscle in muscles))

    def test_legacy_origin_and_offcentre_migrate_without_selection(self):
        root_obj = _setup()
        _select(root_obj, False)
        for muscle, point in zip(root_obj.af_vcp_system.muscles, ((0, 0, 0), (1.3, 3.4, 0.01))):
            _clear_placement(muscle)
            muscle[LEGACY_KEY] = point
        _sync(root_obj)
        for muscle, point in zip(root_obj.af_vcp_system.muscles, ((0, 0, 0), (1.3, 3.4, 0.01))):
            np.testing.assert_allclose(inflation_control_world(muscle), point, atol=1e-7, rtol=0)
            self.assertTrue(inflation_control_initialized(muscle))
        _reload_cycles(self, _state(root_obj), cycles=1)

    def test_explicit_false_initializes_midpoint_instead_of_legacy(self):
        root_obj = _setup()
        muscle = root_obj.af_vcp_system.muscles[0]
        muscle[LEGACY_KEY] = (99, 99, 99)
        muscle.inflation_ctrl_initialized = False
        _select(root_obj, False)
        _sync(root_obj)
        self.assertTrue(inflation_control_initialized(muscle))
        _assert_midpoint(self, root_obj, muscle)

    def test_gizmo_reconstruction_never_snaps_authored_point(self):
        root_obj = _setup()
        _author(root_obj)
        _select(root_obj, True)
        muscle = root_obj.af_vcp_system.muscles[0]
        baseline = _state(root_obj)
        bpy.data.objects.remove(_control(muscle), do_unlink=True)
        sync = register_muscle_sync()
        with patch.object(sync, "_nearest_on_mesh_surface", side_effect=AssertionError("Reconstruction snapped")):
            _sync(root_obj)
        np.testing.assert_allclose(_control(muscle).location, baseline[muscle.id][0], atol=1e-7, rtol=0)
        _assert_state(self, baseline, _state(root_obj))

    def test_real_edit_snaps_and_survives_reload(self):
        root_obj = _setup()
        _select(root_obj, True)
        muscle = root_obj.af_vcp_system.muscles[0]
        ctrl = _control(muscle)
        target = ctrl.location + Vector((0.4, 0, 3))
        expected, _normal = register_muscle_sync()._nearest_on_mesh_surface(_surface_obj(root_obj, muscle, "BASE"), target)
        ctrl.location = target
        self.assertEqual(apply_muscle_control_update(register_muscle_sync(), root_obj, bpy.context.scene, ctrl), muscle.id)
        np.testing.assert_allclose(inflation_control_world(muscle), expected, atol=1e-7, rtol=0)
        _sync(root_obj)
        _reload_cycles(self, _state(root_obj), cycles=1)

    def test_disabled_and_distributed_roundtrips_preserve_authored_point(self):
        root_obj = _setup()
        _author(root_obj)
        baseline = _state(root_obj)
        for enabled, mode in ((False, "CTRL_POINT"), (True, "DISTRIBUTED"), (True, "CTRL_POINT")):
            with suppress_vcp_prop_updates():
                for muscle in root().af_vcp_system.muscles:
                    muscle.inflation_enabled, muscle.inflation_mode = enabled, mode
            _sync(root())
            for key, state in _state(root()).items():
                self.assertEqual(state[:2], baseline[key][:2])
            _reload_cycles(self, _state(root()), cycles=1)
        _assert_state(self, baseline, _state(root()))

    def test_internal_setter_suppresses_property_callbacks(self):
        from anthroforge.properties import vcp_properties
        muscle = root().af_vcp_system.muscles.add()
        with patch.object(vcp_properties, "sync_context") as sync:
            set_inflation_control_world(muscle, (0.3, 0.2, 0.1))
        self.assertEqual(sync.call_count, 0)
