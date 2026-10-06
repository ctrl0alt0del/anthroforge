"""File-wide warnings without solves, and exact navigation/lifecycle contracts."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, root
from test_fiber_anchor_preflight import _scene_fixture, _preflight, _cube_scp, _fiber_with_touch
from anthroforge.core.warnings import session
from anthroforge.core.warnings.query import WarningQuery
from anthroforge.core.visualization import warning_runtime as runtime
from anthroforge.core.visualization.warning_selection import select_warning
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def drain():
    deadline = time.perf_counter() + 15
    while time.perf_counter() < deadline:
        active = session.COORDINATOR.tick(max_steps=32)
        if not runtime.pipeline.reap() and not active: return
        time.sleep(0.002)
    raise AssertionError("Warning scan failed to finish")


def check_all():
    runtime.after_change(None)
    drain()
    return WarningQuery().list()


def extra_root(name):
    value = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(value)
    value["anthroforge_root"] = True
    _cube_scp(value, "Blocker", 4)
    owner, _obj = _cube_scp(value, "Owner", 1)
    insertion, _obj = _cube_scp(value, "Insertion", 1, (6, 0, 0))
    return value, _fiber_with_touch(value, owner, insertion)


def query_api(owner_root, directory, **params):
    from anthroforge.app.authoring.api import execute
    value = dict(version="0.4.0", message_type="request", request_id="warnings", op="warnings.list",
                 params=dict(scene_id=owner_root.name, **params))
    return execute(value, owner_root, bpy.context.scene, directory)


def forbid_solves():
    from contextlib import ExitStack
    from anthroforge.core.vcp import fiber_solver, fiber_v2_runtime, fiber_pin_repair, fiber_planner
    stack = ExitStack()
    targets = ((fiber_solver.FiberSolver, "solve_points"), (fiber_v2_runtime, "begin_v2_runtime"),
               (fiber_v2_runtime, "begin_v3_runtime"), (fiber_pin_repair, "repair_current_preflight_pins"),
               (fiber_planner, "plan_route"))
    for target, name in targets:
        stack.enter_context(patch.object(target, name, side_effect=AssertionError(f"Diagnostic called {name}")))
    return stack


class WarningBlenderTests(BlenderTestCase):
    def test_global_incremental_match_and_fix_clears_without_solve(self):
        owner_root, blocker, _owner, fiber = _scene_fixture()
        expected = _preflight(owner_root, fiber)
        with forbid_solves():
            result = check_all()
            self.assertTrue(result["complete"], result)
            self.assertEqual(result["total"], len(expected.violations))
            runtime.notify_action(owner_root, bpy.context.scene, {"FIBER": {fiber.id}}); drain()
            self.assertEqual([r["id"] for r in WarningQuery().list()["records"]], [r["id"] for r in result["records"]])
            blocker.location.x = 10; bpy.context.view_layer.update()
            runtime.notify_action(owner_root, bpy.context.scene, {"SCP": {"blocker"}}); drain()
            self.assertEqual(WarningQuery().list()["total"], 0)

    def test_load_saved_invalid_file_populates_and_next_file_clears(self):
        _scene_fixture()
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "invalid.blend")
            bpy.ops.wm.save_as_mainfile(filepath=path)
            with forbid_solves():
                bpy.ops.wm.open_mainfile(filepath=path); drain()
            result = WarningQuery().list()
            self.assertEqual(result["total"], 2, result)
            before = result["epoch"]
            bpy.ops.wm.read_factory_settings(use_empty=True)
            self.assertEqual(WarningQuery().list()["total"], 0)
            self.assertNotEqual(WarningQuery().list()["epoch"], before)

    def test_selection_endpoint_and_touch_and_rename(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture()
        check_all(); rows = list(session.REPOSITORY.records.values())
        fiber.name = "Renamed Fiber"
        for row in rows:
            with forbid_solves():
                self.assertTrue(select_warning(bpy.context, row.id), row)
            obj = bpy.context.view_layer.objects.active
            self.assertEqual(obj.get("af_fiber_id"), fiber.id)
            if row.pin.role == "TOUCH":
                self.assertTrue(obj.get("af_fiber_touch_handle"))
            else:
                self.assertEqual(obj.get("af_fiber_endpoint"), "A")

    def test_stale_pin_and_deleted_fiber_never_select_substitute(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture()
        check_all(); row = next(iter(session.REPOSITORY.records.values()))
        with suppress_vcp_prop_updates():
            fiber.mid_touches.clear()
        self.assertFalse(select_warning(bpy.context, row.id))
        runtime.structural_change(owner_root); owner_root.af_vcp_system.fibers.clear()
        runtime.notify_action(owner_root, bpy.context.scene, full=True); drain()
        self.assertEqual(WarningQuery().list()["total"], 0)

    def test_failed_capture_and_cancel_never_report_clean(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture()
        with suppress_vcp_prop_updates():
            fiber.a_attach_param = "missing"
        result = check_all()
        self.assertFalse(result["complete"])
        self.assertGreater(result["counts"]["FAILED"], 0)
        runtime.before_change(None)
        self.assertFalse(WarningQuery().list()["complete"])

    def test_selection_only_event_does_not_queue_checks(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        before = dict(session.COORDINATOR.metrics)
        runtime.notify_action(owner_root, bpy.context.scene, {"FIBER": {fiber.id}}, "SELECTION")
        self.assertFalse(session.COORDINATOR.jobs)
        self.assertEqual(dict(session.COORDINATOR.metrics), before)

    def test_duplicate_ids_across_roots_and_scenes_navigate_owned_target(self):
        first_root, _blocker, _owner, first_fiber = _scene_fixture()
        second_root, second_fiber = extra_root("AF_SECOND")
        bpy.context.window.scene = bpy.data.scenes.new("Other scene")
        third_root, third_fiber = extra_root("AF_THIRD")
        result = check_all()
        self.assertEqual(result["total"], 6, result)
        self.assertEqual(len({row.entity.root for row in session.REPOSITORY.records.values()}), 3)
        selected = next(row for row in session.REPOSITORY.records.values() if row.entity.root == session.id_token(second_root))
        with forbid_solves():
            self.assertTrue(select_warning(bpy.context, selected.id))
        self.assertEqual(bpy.context.scene.name, selected.entity.scene_label)
        from anthroforge.core.utils import get_af_root, clear_scene_cache
        clear_scene_cache(bpy.context.scene)
        self.assertEqual(get_af_root(bpy.context.scene), second_root)

    def test_exact_loop_and_endpoint_b_selection(self):
        owner_root, _blocker, owner, fiber = _scene_fixture()
        with suppress_vcp_prop_updates():
            fiber.b_parent_id, fiber.b_attach_param = fiber.a_parent_id, fiber.a_attach_param
        check_all()
        endpoint = next(row for row in session.REPOSITORY.records.values() if row.pin.role == "ENDPOINT_B")
        self.assertTrue(select_warning(bpy.context, endpoint.id))
        self.assertEqual(bpy.context.object.get("af_fiber_endpoint"), "B")
        make_loop(fiber); runtime.structural_change(owner_root); check_all()
        with forbid_solves():
            for row in tuple(session.REPOSITORY.records.values()):
                self.assertTrue(select_warning(bpy.context, row.id), row)
                self.assertTrue(bpy.context.object.get("af_fiber_loop_anchor_handle"))
                self.assertEqual(bpy.context.object.get("af_fiber_loop_anchor_index"), row.pin.index)

    def test_query_bypasses_scene_capture_and_matches_ui_and_compatibility(self):
        from anthroforge.adapters.authoring.native_scene import BlenderScene
        from anthroforge.core.vcp.fiber_anchor_preflight import current_fiber_anchor_preflight
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        with TemporaryDirectory() as directory, forbid_solves():
            with patch.object(BlenderScene, "capture", side_effect=AssertionError("Query captured geometry")):
                result = query_api(owner_root, directory)
        self.assertEqual(result["warnings"]["total"], 2, result)
        self.assertEqual(len(bpy.context.window_manager.af_warning_rows), 2)
        self.assertEqual(len(current_fiber_anchor_preflight(bpy.context.scene, owner_root, fiber).violations), 2)

    def test_enable_history_and_reload_rotate_old_tokens(self):
        _scene_fixture(); check_all()
        old = next(iter(session.REPOSITORY.records))
        runtime.before_change(None); runtime.after_change(None); drain()
        self.assertNotIn(old, session.REPOSITORY.records)
        self.assertEqual(WarningQuery().list()["total"], 2)
        runtime.unregister()
        self.assertFalse(WarningQuery().list()["complete"])
        runtime.register(); drain()
        self.assertEqual(WarningQuery().list()["total"], 2)

    def test_projection_clears_before_save_without_restoring_old_payload(self):
        from anthroforge.ui import warnings
        _scene_fixture(); check_all()
        self.assertEqual(len(bpy.context.window_manager.af_warning_rows), 2)
        warnings.clear_projection(None)
        self.assertEqual(len(bpy.context.window_manager.af_warning_rows), 0)
        self.assertEqual(WarningQuery().list()["total"], 2)
        warnings.restore_projection(None)
        self.assertEqual(len(bpy.context.window_manager.af_warning_rows), 2)


def make_loop(fiber):
    with suppress_vcp_prop_updates():
        fiber.topology_mode = "LOOP"
        for _index in range(3):
            pin = fiber.loop_anchors.add()
            pin.parent_id, pin.attach_param = fiber.a_parent_id, fiber.a_attach_param


if __name__ == "__main__":
    unittest.main()
