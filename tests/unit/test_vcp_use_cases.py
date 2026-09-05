from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core.vcp.runtime_state import (
    fiber_eps_disp,
    fiber_eps_pen,
    fiber_recompute_ms,
    fiber_recompute_status,
    set_fiber_eps_disp,
    set_fiber_eps_pen,
    set_fiber_recompute_ms,
    set_fiber_recompute_status,
)
from app.use_cases.blob_create import create_blob_vcp
from app.use_cases.blob_tools import select_blob_control
from app.use_cases.fiber_create import _common_mirror_rule, _validate_symmetric_points, create_fiber_from_proxy_vertices, create_fiber_vcp
from app.use_cases.fiber_tools import add_fiber_touch_point, add_fiber_touch_point_at_world, clear_fiber_warm_start, move_fiber_touch_point, recompute_fiber, remove_fiber_touch_point
from app.use_cases.muscle_create import create_muscle_vcp
from app.use_cases.muscle_tools import flip_muscle_normals, select_muscle_inflation_ctrl
from app.use_cases.vcp_delete import delete_vcp_in_tree


class Bag(dict):
    def __init__(self, **values):
        super().__init__(**values)
        self.__dict__ = self


class FakeCollection(list):
    def add(self):
        item = Bag(fiber_refs=FakeCollection(), mid_touches=FakeCollection())
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)

    def move(self, old_index, new_index):
        self.insert(int(new_index), self.pop(int(old_index)))


class FakeSelectable(Bag):
    def __init__(self, name, **values):
        super().__init__(name=name, selected=False, **values)

    def select_set(self, value):
        self.selected = bool(value)

    def select_get(self):
        return bool(self.selected)


def root(fibers=(), muscles=(), blobs=(), active_type="NONE", active_id="", scps=()):
    vcp = Bag(fibers=list(fibers), muscles=list(muscles), blobs=list(blobs), active_vcp_type=active_type, active_vcp_id=active_id)
    scp = Bag(scps=list(scps), active_scp_index=0)
    return Bag(name="ROOT", anthroforge_root=True, af_vcp_system=vcp, af_scp_system=scp)


def scene(*objects):
    return SimpleNamespace(
        objects=list(objects),
        cursor=SimpleNamespace(location=(0.0, 0.0, 0.0)),
        af_selection_order_json="[]",
        af_new_fiber_origin_obj=None,
        af_new_fiber_insertion_obj=None,
        af_new_blob_target_obj=None,
    )


def context(scene_obj, active_object=None, selected_objects=()):
    layer = SimpleNamespace(objects=SimpleNamespace(active=None))
    return SimpleNamespace(scene=scene_obj, active_object=active_object, selected_objects=list(selected_objects), view_layer=layer)


def _vcp_root(fibers=(), muscles=(), blobs=(), active_type="NONE", active_id=""):
    root_obj = root(active_type=active_type, active_id=active_id)
    root_obj.af_vcp_system.fibers = FakeCollection(list(fibers))
    root_obj.af_vcp_system.muscles = FakeCollection(list(muscles))
    root_obj.af_vcp_system.blobs = FakeCollection(list(blobs))
    return root_obj


def _run_delete(root_obj, node_type, node_id):
    synced, cleared, cleaned = [], [], []
    muscle_sync = SimpleNamespace(sync_root_to_scene=lambda **kwargs: cleaned.append(kwargs))
    with patch("app.use_cases.vcp_delete._fiber_sync", return_value=SimpleNamespace(clear_solver_cache=cleared.append)):
        with patch("app.use_cases.vcp_delete._muscle_sync", return_value=muscle_sync), patch("app.use_cases.vcp_delete._empty_dirty_hints", return_value=lambda: "HINTS"), patch("app.use_cases.vcp_delete._sync_scene", return_value=lambda **kwargs: synced.append(kwargs)):
            result = delete_vcp_in_tree(context(scene(root_obj)), node_type, node_id)
    return result, synced, cleared, cleaned


class VcpUseCaseTests(unittest.TestCase):
    def test_create_fiber_vcp_initializes_and_syncs(self):
        root_obj = root()
        root_obj.af_vcp_system.fibers = FakeCollection()
        calls = []
        ctx = context(scene(root_obj))
        sync = SimpleNamespace(refresh_selection=lambda **_kwargs: None)
        with patch("app.use_cases.fiber_create._resolved_inputs", return_value=("S1", "S2", "A", "B")):
            with patch("app.use_cases.fiber_create._sync_entity", side_effect=lambda *args: calls.append(args)):
                with patch("app.use_cases.fiber_create._fiber_sync", return_value=sync):
                    result = create_fiber_vcp(ctx)
        fiber = root_obj.af_vcp_system.fibers[0]
        self.assertTrue(result.ok)
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id), ("S1", "S2"))
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id), ("FIBER", fiber.id))
        self.assertEqual(calls[0][2:], ("FIBER", {fiber.id}))

    def test_create_fiber_from_proxy_vertices_fails_when_mid_capture_fails(self):
        root_obj = root()
        root_obj.af_vcp_system.fibers = FakeCollection()
        picks = [Bag(scp_id="S1", vertex_index=1), Bag(scp_id="S2", vertex_index=2), Bag(scp_id="S3", vertex_index=3)]
        ctx = context(scene(root_obj))
        with patch("app.use_cases.fiber_create._selected_proxy_vertices", return_value=lambda _ctx: (picks, "")):
            with patch("app.use_cases.fiber_create._proxy_attach", side_effect=["A_RAW", "B_RAW", None]):
                result = create_fiber_from_proxy_vertices(ctx)
        self.assertFalse(result.ok)
        self.assertEqual(len(root_obj.af_vcp_system.fibers), 0)
        self.assertIn("S2", result.message)
        self.assertIn("vertex 2", result.message)

    def test_symmetric_loop_rule_uses_compatible_common_ancestor(self):
        scps = [
            Bag(id="S1", parent_id="", mirror_enabled=True, mirror_axis="X", mirror_origin=(0.0, 0.0, 0.0)),
            Bag(id="S2", parent_id="S1", mirror_enabled=True, mirror_axis="X", mirror_origin=(0.0, 0.0, 0.0)),
            Bag(id="S3", parent_id="S1", mirror_enabled=False, mirror_inherit_parent=False, mirror_axis="X"),
        ]
        rule, error = _common_mirror_rule(root(scps=scps), ("S2", "S3"))
        self.assertEqual((rule, error), (("X", (0.0, 0.0, 0.0)), ""))

    def test_symmetric_loop_validation_accepts_off_plane_half_loop(self):
        specs = (("S1", "A", (0.03, 0.0, 0.0)), ("S2", "B", (0.2, 0.0, 0.0)), ("S3", "C", (0.04, 0.0, 0.0)))
        self.assertEqual(_validate_symmetric_points(specs, ("X", (0.0, 0.0, 0.0))), "")

    def test_create_muscle_vcp_assigns_selected_fibers(self):
        fiber1 = Bag(id="F1", node_count=8, mid_touches=[], muscle_id="")
        fiber2 = Bag(id="F2", node_count=8, mid_touches=[], muscle_id="")
        old = Bag(id="OLD", fiber_refs=FakeCollection([Bag(fiber_id="F2")]))
        root_obj = root(fibers=[fiber1, fiber2])
        root_obj.af_vcp_system.muscles = FakeCollection([old])
        proxy1 = FakeSelectable("P1", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F1")
        proxy2 = FakeSelectable("P2", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F2")
        proxy1.select_set(True)
        proxy2.select_set(True)
        ctx = context(scene(root_obj, proxy1, proxy2), active_object=proxy1, selected_objects=[proxy1, proxy2])
        with patch("app.use_cases.muscle_create._sync_entity", return_value=None):
            with patch("app.use_cases.muscle_create._find_ctrl", return_value=None):
                result = create_muscle_vcp(ctx)
        muscle = root_obj.af_vcp_system.muscles[-1]
        refs = {ref.fiber_id for ref in muscle.fiber_refs}
        self.assertTrue(result.ok)
        self.assertEqual(refs, {"F1", "F2"})
        self.assertEqual(muscle.inflation_mode, "CTRL_POINT")
        self.assertEqual((fiber1.muscle_id, fiber2.muscle_id), (muscle.id, muscle.id))
        self.assertEqual(len(old.fiber_refs), 0)

    def test_create_muscle_vcp_uses_tracked_selection_order(self):
        fibers = [Bag(id=f"F{i}", node_count=8, mid_touches=[], muscle_id="") for i in range(1, 4)]
        root_obj = root(fibers=fibers)
        root_obj.af_vcp_system.muscles = FakeCollection()
        proxies = [FakeSelectable(f"P{i}", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id=f"F{i}") for i in range(1, 4)]
        for obj in proxies:
            obj.select_set(True)
        scn = scene(root_obj, *proxies)
        scn.af_selection_order_json = '["P1","P2","P3"]'
        ctx = context(scn, active_object=proxies[2], selected_objects=[proxies[2], proxies[0], proxies[1]])
        with patch("app.use_cases.muscle_create._sync_entity", return_value=None), patch("app.use_cases.muscle_create._find_ctrl", return_value=None):
            result = create_muscle_vcp(ctx)
        self.assertTrue(result.ok)
        self.assertEqual([ref.fiber_id for ref in root_obj.af_vcp_system.muscles[0].fiber_refs], ["F1", "F2", "F3"])

    def test_create_muscle_vcp_stores_mirrored_row_mode(self):
        fiber1 = Bag(id="F1", node_count=8, mid_touches=[], muscle_id="")
        fiber2 = Bag(id="F2", node_count=8, mid_touches=[], muscle_id="")
        root_obj = root(fibers=[fiber1, fiber2]); root_obj.af_vcp_system.muscles = FakeCollection()
        proxy1 = FakeSelectable("P1", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F1")
        proxy2 = FakeSelectable("P2", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F2")
        proxy1.select_set(True); proxy2.select_set(True)
        ctx = context(scene(root_obj, proxy1, proxy2), active_object=proxy1, selected_objects=[proxy1, proxy2])
        with patch("app.use_cases.muscle_create._sync_entity", return_value=None), patch("app.use_cases.muscle_create._find_ctrl", return_value=None):
            result = create_muscle_vcp(ctx, use_mirrored_rows=True)
        self.assertTrue(result.ok)
        self.assertTrue(root_obj.af_vcp_system.muscles[0].use_mirrored_rows)

    def test_create_muscle_vcp_allows_single_mirrored_fiber(self):
        fiber = Bag(id="F1", node_count=8, mid_touches=[], muscle_id="", a_parent_id="S1", b_parent_id="S1")
        scp = Bag(id="S1", mirror_enabled=True, mirror_axis="X", mirror_origin=(0.0, 0.0, 0.0), parent_id="", mirror_inherit_parent=True)
        root_obj = root(fibers=[fiber], scps=[scp]); root_obj.af_vcp_system.muscles = FakeCollection()
        proxy = FakeSelectable("P1", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F1")
        proxy.select_set(True)
        ctx = context(scene(root_obj, proxy), active_object=proxy, selected_objects=[proxy])
        with patch("app.use_cases.muscle_create._sync_entity", return_value=None), patch("app.use_cases.muscle_create._find_ctrl", return_value=None):
            result = create_muscle_vcp(ctx)
        self.assertTrue(result.ok)
        self.assertEqual([ref.fiber_id for ref in root_obj.af_vcp_system.muscles[0].fiber_refs], ["F1"])
        self.assertTrue(root_obj.af_vcp_system.muscles[0].use_mirrored_rows)

    def test_create_muscle_vcp_rejects_incompatible_fibers(self):
        fiber1 = Bag(id="F1", node_count=8, mid_touches=[], muscle_id="")
        fiber2 = Bag(id="F2", node_count=9, mid_touches=[], muscle_id="")
        root_obj = root(fibers=[fiber1, fiber2])
        root_obj.af_vcp_system.muscles = FakeCollection()
        proxy1 = FakeSelectable("P1", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F1")
        proxy2 = FakeSelectable("P2", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F2")
        proxy1.select_set(True)
        proxy2.select_set(True)
        ctx = context(scene(root_obj, proxy1, proxy2), active_object=proxy1, selected_objects=[proxy1, proxy2])
        result = create_muscle_vcp(ctx)
        self.assertEqual((result.ok, result.message), (False, "Selected fibers must have identical node_count."))

    def test_create_muscle_vcp_allows_different_mid_touch_counts(self):
        fiber1 = Bag(id="F1", node_count=8, mid_touches=[], muscle_id="")
        fiber2 = Bag(id="F2", node_count=8, mid_touches=[Bag(parent_id="S1")], muscle_id="")
        root_obj = root(fibers=[fiber1, fiber2]); root_obj.af_vcp_system.muscles = FakeCollection()
        proxy1 = FakeSelectable("P1", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F1")
        proxy2 = FakeSelectable("P2", af_fiber_proxy=True, af_root_name="ROOT", af_fiber_id="F2")
        proxy1.select_set(True); proxy2.select_set(True)
        ctx = context(scene(root_obj, proxy1, proxy2), active_object=proxy1, selected_objects=[proxy1, proxy2])
        with patch("app.use_cases.muscle_create._sync_entity", return_value=None), patch("app.use_cases.muscle_create._find_ctrl", return_value=None):
            result = create_muscle_vcp(ctx)
        self.assertTrue(result.ok)

    def test_create_blob_vcp_sets_target_and_syncs(self):
        root_obj = root()
        root_obj.af_vcp_system.blobs = FakeCollection()
        target = FakeSelectable("Muscle", af_muscle_proxy=True, af_muscle_id="M1")
        scn = scene(root_obj, target)
        scn.af_new_blob_target_obj = target
        calls = []
        with patch("app.use_cases.blob_create._sync_entity", side_effect=lambda *args: calls.append(args)):
            result = create_blob_vcp(context(scn, active_object=target))
        blob = root_obj.af_vcp_system.blobs[0]
        self.assertTrue(result.ok)
        self.assertEqual((blob.attach_target_type, blob.attach_target_id), ("MUSCLE", "M1"))
        self.assertEqual(calls[0][2:], ("BLOB", {blob.id}))

    def test_clear_fiber_warm_start_resets_runtime_fields(self):
        fiber = Bag(id="F1")
        set_fiber_recompute_status(fiber, "CONVERGED")
        set_fiber_recompute_ms(fiber, 9.0)
        set_fiber_eps_disp(fiber, 3.0)
        set_fiber_eps_pen(fiber, 4.0)
        root_obj = root(fibers=[fiber], active_type="FIBER", active_id="F1")
        calls = []
        ctx = context(scene(root_obj))
        with patch("app.use_cases.fiber_tools._fiber_sync", return_value=SimpleNamespace(clear_solver_cache=calls.append)), \
             patch("app.use_cases.fiber_tools._clear_v3_warm") as clear_v3:
            result = clear_fiber_warm_start(ctx)
        self.assertTrue(result.ok)
        self.assertEqual(calls, ["F1"])
        clear_v3.assert_called_once_with(ctx, root_obj, fiber)
        self.assertEqual((fiber_recompute_status(fiber), fiber_recompute_ms(fiber)), ("UNKNOWN", 0.0))
        self.assertEqual((fiber_eps_disp(fiber), fiber_eps_pen(fiber)), (0.0, 0.0))

    def test_recompute_fiber_enqueues_background_refinement(self):
        fiber = Bag(id="F1")
        root_obj = root(fibers=[fiber], active_type="FIBER", active_id="F1")
        ctx = context(scene(root_obj))
        request = SimpleNamespace(ok=True, error="")
        runner = Mock(return_value=request)
        with patch("app.use_cases.fiber_tools._request_refinement", return_value=runner):
            result = recompute_fiber(ctx)
        self.assertTrue(result.ok)
        runner.assert_called_once_with(root_obj, ctx.scene, fiber, show_preview=True)
        self.assertIn("background", result.message)

    def test_recompute_fiber_reports_enqueue_failure(self):
        fiber = Bag(id="F1")
        ctx = context(scene(root(fibers=[fiber], active_type="FIBER", active_id="F1")))
        request = SimpleNamespace(ok=False, error="No collision route")
        with patch("app.use_cases.fiber_tools._request_refinement", return_value=Mock(return_value=request)):
            result = recompute_fiber(ctx)
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "No collision route")

    def test_add_and_remove_fiber_touch_point_sync_runtime(self):
        fiber = Bag(id="F1", mid_touches=FakeCollection())
        root_obj = root(fibers=[fiber], active_type="FIBER", active_id="F1")
        ctx = context(scene(root_obj))
        cleared, synced = [], []
        sync = SimpleNamespace(clear_solver_cache=cleared.append)
        with patch("app.use_cases.fiber_tools._resolved_touch", return_value=(fiber, "S1", "RAW")):
            with patch("app.use_cases.fiber_tools._fiber_sync", return_value=sync):
                with patch("app.use_cases.fiber_tools._sync_entity", side_effect=lambda *args, **kwargs: synced.append((args, kwargs))):
                    self.assertTrue(add_fiber_touch_point(ctx).ok)
                    self.assertTrue(remove_fiber_touch_point(ctx, touch_index=0).ok)
        self.assertEqual((len(fiber.mid_touches), cleared), (0, ["F1", "F1"]))
        self.assertEqual(len(synced), 2)

    def test_add_fiber_touch_point_at_world_captures_pick(self):
        fiber = Bag(id="F1", mid_touches=FakeCollection())
        root_obj = root(fibers=[fiber], active_type="FIBER", active_id="F1")
        ctx = context(scene(root_obj))
        with patch("app.use_cases.fiber_tools._capture_attachment_from_world", return_value=lambda *_args: "RAW"):
            with patch("app.use_cases.fiber_tools._fiber_sync", return_value=SimpleNamespace(clear_solver_cache=lambda *_a: None)):
                with patch("app.use_cases.fiber_tools._sync_entity", return_value=None):
                    result = add_fiber_touch_point_at_world(ctx, "F1", "S1", (1.0, 2.0, 3.0))
        self.assertTrue(result.ok)
        self.assertEqual((fiber.mid_touches[0].parent_id, fiber.mid_touches[0].attach_param), ("S1", "RAW"))

    def test_move_fiber_touch_point_reorders_and_syncs(self):
        touches = FakeCollection([Bag(parent_id="A"), Bag(parent_id="B")])
        fiber = Bag(id="F1", mid_touches=touches)
        ctx = context(scene(root(fibers=[fiber], active_type="FIBER", active_id="F1")))
        synced = []
        with patch("app.use_cases.fiber_tools._fiber_sync", return_value=SimpleNamespace(clear_solver_cache=lambda *_a: None)):
            with patch("app.use_cases.fiber_tools._sync_entity", side_effect=lambda *args, **kwargs: synced.append((args, kwargs))):
                result = move_fiber_touch_point(ctx, "F1", 1, -1)
        self.assertTrue(result.ok)
        self.assertEqual([touch.parent_id for touch in fiber.mid_touches], ["B", "A"])
        self.assertEqual(len(synced), 1)

    def test_flip_muscle_normals_toggles_and_syncs(self):
        muscle = Bag(id="M1", flip_normals=False)
        root_obj = root(muscles=[muscle], active_type="MUSCLE", active_id="M1")
        calls = []
        with patch("app.use_cases.muscle_tools._sync_entity", side_effect=lambda *args: calls.append(args)):
            result = flip_muscle_normals(context(scene(root_obj)))
        self.assertTrue(result.ok)
        self.assertTrue(muscle.flip_normals)
        self.assertEqual(calls[0][2:], ("MUSCLE", {"M1"}))

    def test_select_muscle_inflation_ctrl_updates_selection_and_active_vcp(self):
        muscle = Bag(id="M1")
        root_obj = root(muscles=[muscle], active_type="MUSCLE", active_id="M1")
        other = FakeSelectable("Other")
        ctrl = FakeSelectable("Ctrl", af_muscle_inflation_ctrl=True, af_root_name="ROOT", af_muscle_id="M1")
        other.select_set(True)
        ctx = context(scene(root_obj, other, ctrl), selected_objects=[other])
        with patch("app.use_cases.muscle_tools._sync_entity", return_value=None):
            with patch("app.use_cases.muscle_tools._find_proxy", return_value=other):
                with patch("app.use_cases.muscle_tools._find_ctrl", return_value=ctrl):
                    result = select_muscle_inflation_ctrl(ctx)
        self.assertTrue(result.ok)
        self.assertEqual((other.selected, ctrl.selected), (False, True))
        self.assertIs(ctx.view_layer.objects.active, ctrl)
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id), ("MUSCLE", "M1"))

    def test_select_muscle_inflation_ctrl_fails_for_distributed_mode(self):
        muscle = Bag(id="M1", inflation_mode="DISTRIBUTED")
        root_obj = root(muscles=[muscle], active_type="MUSCLE", active_id="M1")
        result = select_muscle_inflation_ctrl(context(scene(root_obj)))
        self.assertEqual((result.ok, result.message), (False, "Inflation control is only available in CTRL_POINT mode."))

    def test_select_blob_control_updates_selection_and_active_vcp(self):
        blob = Bag(id="B1")
        root_obj = root(blobs=[blob], active_type="BLOB", active_id="B1")
        other = FakeSelectable("Other")
        ctrl = FakeSelectable("Ctrl", af_blob_control_gizmo=True, af_root_name="ROOT", af_blob_id="B1")
        other.select_set(True)
        ctx = context(scene(root_obj, other, ctrl), selected_objects=[other])
        with patch("app.use_cases.blob_tools._sync_entity", return_value=None):
            with patch("app.use_cases.blob_tools._find_proxy", return_value=other):
                with patch("app.use_cases.blob_tools._find_ctrl", return_value=ctrl):
                    result = select_blob_control(ctx)
        self.assertTrue(result.ok)
        self.assertEqual((other.selected, ctrl.selected), (False, True))
        self.assertIs(ctx.view_layer.objects.active, ctrl)
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id), ("BLOB", "B1"))

    def test_delete_vcp_in_tree_removes_fiber_and_muscle_refs(self):
        fiber = Bag(id="F1", muscle_id="M1", mid_touches=FakeCollection())
        muscle = Bag(id="M1", fiber_refs=FakeCollection([Bag(fiber_id="F1")]))
        root_obj = _vcp_root([fiber], [muscle], active_type="FIBER", active_id="F1")
        result, synced, cleared, cleaned = _run_delete(root_obj, "FIBER", "F1")
        self.assertTrue(result.ok)
        self.assertEqual((len(root_obj.af_vcp_system.fibers), len(muscle.fiber_refs), cleared, cleaned), (0, 0, ["F1"], []))
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, synced[0]["event_type"]), ("NONE", "DELETE"))

    def test_delete_vcp_in_tree_removes_muscle_and_clears_fibers(self):
        fibers = [Bag(id="F1", muscle_id="M1"), Bag(id="F2", muscle_id="M1")]
        refs = FakeCollection([Bag(fiber_id="F1"), Bag(fiber_id="F2")])
        root_obj = _vcp_root(fibers, [Bag(id="M1", fiber_refs=refs)], active_type="MUSCLE", active_id="M1")
        result, synced, cleared, cleaned = _run_delete(root_obj, "MUSCLE", "M1")
        self.assertTrue(result.ok)
        self.assertEqual((len(root_obj.af_vcp_system.muscles), [f.muscle_id for f in fibers], cleared), (0, ["", ""], []))
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, synced), ("NONE", []))
        self.assertEqual(cleaned[0]["target_muscle_ids"], set())


if __name__ == "__main__":
    unittest.main()
