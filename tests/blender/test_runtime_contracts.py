from pathlib import Path
from collections import OrderedDict
from types import SimpleNamespace
import sys
from unittest.mock import Mock, patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, capture_mesh_attachment, empty_object, fiber, mesh_object, root, scp_with_object, temp_blend_path
from app.context import AddonContext
from app.runtime_requests import RuntimeRequest
from core.deps.drivers import DependencyDriver
from core.id_utils import next_prefixed_id
from core.scp_runtime.attachment_runtime import apply_scp_attachments
from core.scp_runtime.common import scp_prop_map
from core.scp_runtime.lookup import set_parent_relation
from core.scp_runtime.runtime_state import attach_initialized, mirror_effective_axis, mirror_source_id, mirror_status
from core.utils import get_af_root
from core.vcp.runtime_state import fiber_recompute_ms, fiber_recompute_status, set_fiber_recompute_ms, set_fiber_recompute_status
from core.visualization.scp_control_helpers import mark_scp_control_object
from core.visualization import control_runtime, delete_reconcile, sync_runner
from core.deps import builtin_drivers, drivers, gates, runtime, runtime_intent_behaviors, runtime_intents


def _restore_addon():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()


def _handler_count(seq, fn):
    return sum(item is fn for item in tuple(seq))


def _reset_sync_runner():
    sync_runner.clear_pending_runtime(keep_timer=False)


def _save_load_fixture():
    root_obj = root()
    parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
    child = scp_with_object(root_obj, "Child", mesh_object("Child", (1.0, 0.0, 0.0)))
    set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
    _configure_scp(parent, child)
    fib, muscle, blob = _configure_vcps(root_obj, parent, child)
    add_shortcut(root_obj, "Child X", "SCP", child.id, "location[0]")
    return temp_blend_path(), (parent.id, child.id, fib.id, muscle.id, blob.id)


def _configure_scp(parent, child):
    parent.mirror_enabled, parent.mirror_axis = True, "Y"
    parent.mirror_origin = (1.0, 2.0, 3.0)
    child.attach_parent_anchor_mode, child.attach_child_anchor_mode = "OBJECT_ORIGIN", "OBJECT_ORIGIN"
    child.attach_follow_rotation, child.attach_tangent_strategy = False, "STABLE_SURFACE"


def _configure_vcps(root_obj, parent, child):
    fib = fiber(root_obj, parent.id, child.id)
    fib.a_attach_param = capture_mesh_attachment(root_obj, parent, 0)
    fib.b_attach_param = capture_mesh_attachment(root_obj, child, 0)
    fib.node_count, fib.thickness = 24, 0.02
    fib.mid_touches.add().parent_id, fib.mid_touches[0].attach_param = parent.id, capture_mesh_attachment(root_obj, parent, 1)
    set_fiber_recompute_status(fib, "CONVERGED")
    set_fiber_recompute_ms(fib, 12.3)
    muscle = _new_muscle(root_obj, fib.id)
    muscle.closed_v, muscle.flip_normals = True, True
    blob = _new_blob(root_obj, muscle.id)
    blob.shape, blob.radius = "ELLIPSOID", 0.5
    return fib, muscle, blob


def _new_muscle(root_obj, fiber_id):
    item = root_obj.af_vcp_system.muscles.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    item.name = item.id
    item.closed_v = True
    item.fiber_refs.add().fiber_id = fiber_id
    return item


def _new_blob(root_obj, muscle_id):
    item = root_obj.af_vcp_system.blobs.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.blobs, "BLOB")
    item.name = item.id
    item.attach_target_type, item.attach_target_id = "MUSCLE", muscle_id
    item.radius = 0.5
    return item


def _saved_authoring(root_obj, ids):
    parent_id, child_id, fiber_id, muscle_id, blob_id = ids
    parent = next(item for item in root_obj.af_scp_system.scps if item.id == parent_id)
    child = next(item for item in root_obj.af_scp_system.scps if item.id == child_id)
    fiber_prop = next(item for item in root_obj.af_vcp_system.fibers if item.id == fiber_id)
    muscle = next(item for item in root_obj.af_vcp_system.muscles if item.id == muscle_id)
    blob = next(item for item in root_obj.af_vcp_system.blobs if item.id == blob_id)
    return parent, child, fiber_prop, muscle, blob


def _assert_saved_authoring(ids):
    root_obj = get_af_root(bpy.context.scene)
    assert root_obj is not None
    parent, child, fib, muscle, blob = _saved_authoring(root_obj, ids)
    assert child.parent_id == parent.id and parent.mirror_enabled and parent.mirror_axis == "Y"
    assert attach_initialized(child)
    assert mirror_status(parent) == "SOURCE"
    assert (mirror_status(child), mirror_source_id(child), mirror_effective_axis(child)) == ("TARGET", parent.id, "Y")
    assert tuple(round(v, 4) for v in parent.mirror_origin) == (1.0, 2.0, 3.0)
    assert (child.attach_follow_rotation, child.attach_tangent_strategy) == (False, "STABLE_SURFACE")
    assert (fib.a_parent_id, fib.b_parent_id, fib.mid_touches[0].parent_id) == (parent.id, child.id, parent.id)
    assert round(fib.thickness, 4) == 0.02
    assert (fiber_recompute_status(fib), fiber_recompute_ms(fib)) == ("UNKNOWN", 0.0)
    assert (muscle.fiber_refs[0].fiber_id, muscle.closed_v, muscle.flip_normals) == (fib.id, True, True)
    assert (blob.attach_target_type, blob.attach_target_id, root_obj.af_shortcut_system.shortcuts[0].owner_id) == ("MUSCLE", muscle.id, child.id)
    assert round(blob.radius, 4) == 0.5
    return root_obj, parent, child


class RecorderDriver(DependencyDriver):
    name = "recorder"

    def __init__(self, calls):
        self.calls = calls

    def entity_types(self):
        return ("SCP",)

    def build_graph(self, root, graph, entity_sets):
        _ = root, graph
        entity_sets["SCP"].update({"S1", "S2"})

    def sync(self, root, scene, is_full, impacted, bake, gate_meta=None):
        _ = root, scene, bake, gate_meta
        self.calls.append(("sync", bool(is_full), set(impacted.get("SCP", set()))))

    def post_sync(self, root, scene, is_full, impacted, bake):
        _ = root, scene, is_full, bake
        self.calls.append(("post", set(impacted.get("SCP", set()))))


class RuntimeContractTests(BlenderTestCase):
    def test_register_cycle_restores_properties_and_handlers(self):
        import anthroforge
        from anthroforge.core.visualization import control_runtime as package_control_runtime
        from anthroforge.core.visualization import delete_reconcile as package_delete_reconcile
        from anthroforge.core.visualization import sync_runner as package_sync_runner
        self.addCleanup(_restore_addon)
        anthroforge.unregister()
        self.assertFalse(hasattr(bpy.types.Object, "af_scp_system"))
        anthroforge.register()
        self.assertTrue(hasattr(bpy.types.Object, "af_scp_system"))
        self.assertEqual(_handler_count(bpy.app.handlers.undo_pre, package_sync_runner._on_history_pre), 1)
        self.assertEqual(_handler_count(bpy.app.handlers.undo_pre, package_control_runtime._on_history_pre), 1)
        self.assertEqual(_handler_count(bpy.app.handlers.redo_pre, package_control_runtime._on_history_pre), 1)
        self.assertEqual(_handler_count(bpy.app.handlers.load_post, package_control_runtime._on_load_post), 1)
        self.assertEqual(_handler_count(bpy.app.handlers.load_post, package_delete_reconcile._on_load_post), 1)

    def test_load_save_hooks_remove_transient_controls_and_reset_runtime(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Root", empty_object("Scp"))
        temp = empty_object("Temp")
        keep = mark_scp_control_object(empty_object("Keep"), root_obj, scp.id)
        temp_name, keep_name = temp.name, keep.name
        temp["af_fiber_endpoint_handle"] = True
        control_runtime.register_control_runtime()._last_active = ("SCP", "OLD")
        delete_reconcile.register_delete_reconcile()._owners[root_obj.name] = {("SCP", scp.id, "BOUND")}
        with patch.object(control_runtime, "_hydrate_load_state") as hydrate:
            control_runtime._on_save_pre(None)
            control_runtime._on_load_post(None)
        delete_reconcile._on_load_post(None)
        self.assertEqual((bpy.data.objects.get(temp_name), bpy.data.objects.get(keep_name) is not None), (None, True))
        self.assertEqual(control_runtime._CONTROL_RUNTIME._last_active, ("NONE", ""))
        self.assertEqual((hydrate.call_count, delete_reconcile._DELETE_RECONCILE._owners), (1, {}))

    def test_save_reload_preserves_authored_relationships(self):
        path, ids = _save_load_fixture()
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
        root_obj, parent, child = _assert_saved_authoring(ids)
        parent.transform_object_ref.location.x = 2.0
        apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})
        self.assertEqual(tuple(round(v, 4) for v in child.transform_object_ref.location), (3.0, 0.0, 0.0))

    def test_schedule_sync_preserves_event_metadata(self):
        self.addCleanup(_reset_sync_runner)
        _reset_sync_runner()
        root_obj = root()
        with patch.object(sync_runner, "run_dependency_runtime") as run, patch.object(bpy.app.timers, "register") as arm:
            payload = {"scp_apply_parent_ids": ["S1"], "scp_recapture_ids": ["S1"], "non_source_ids_by_type": {"SCP": ["S2"]}}
            sync_runner.schedule_sync_from_dirty_hints(root=root_obj, scene=bpy.context.scene, dirty_hints={"SCP": {"S1"}}, source="depsgraph", event_type="DELETE", payload=payload)
            sync_runner._flush_pending()
            sync_runner._flush_pending()
        meta = run.call_args.kwargs["gate_meta"]
        self.assertEqual((arm.call_count, meta["source"], meta["event_type"]), (1, "depsgraph", "DELETE"))
        self.assertEqual(meta["payload"]["scp_apply_parent_ids"], ["S1"])
        self.assertEqual(meta["payload"]["non_source_ids_by_type"]["SCP"], ["S2"])

    def test_schedule_sync_keeps_pending_request_when_runner_busy(self):
        self.addCleanup(_reset_sync_runner)
        _reset_sync_runner()
        sync_runner._RUNNING = True
        with patch.object(sync_runner, "run_dependency_runtime") as run, patch.object(bpy.app.timers, "register") as arm:
            sync_runner.schedule_sync_from_dirty_hints(root=root(), scene=bpy.context.scene, dirty_hints={"SCP": {"S1"}}, source="depsgraph", payload={"scp_apply_parent_ids": ["S1"]})
            self.assertEqual((sync_runner._flush_pending(), len(sync_runner._PENDING), run.call_count, arm.call_count), (0.0, 1, 0, 1))
            sync_runner._RUNNING = False
            sync_runner._flush_pending()
        self.assertEqual((len(sync_runner._PENDING), run.call_args.kwargs["gate_meta"]["payload"]["scp_apply_parent_ids"]), (0, ["S1"]))

    def test_schedule_sync_queues_explicit_context_and_request_objects(self):
        self.addCleanup(_reset_sync_runner)
        _reset_sync_runner()
        root_obj = root()
        sync_runner.schedule_sync_from_dirty_hints(root=root_obj, scene=bpy.context.scene, dirty_hints={"SCP": {"S1"}}, source="depsgraph", event_type="DELETE", payload={"scp_recapture_ids": ["S1"]})
        item = sync_runner._PENDING[0]
        ctx, request = sync_runner._resolve_item(item)
        self.assertEqual((isinstance(ctx, AddonContext), isinstance(request, RuntimeRequest)), (True, True))
        self.assertEqual((item.root_name, item.scene_name, request.source, request.event_type), (root_obj.name, bpy.context.scene.name, "depsgraph", "DELETE"))
        self.assertEqual(request.payload["scp_recapture_ids"], ["S1"])

    def test_undo_pre_clears_pending_runtime(self):
        self.addCleanup(_reset_sync_runner)
        _reset_sync_runner()
        sync_runner.schedule_sync_from_dirty_hints(root=root(), scene=bpy.context.scene, dirty_hints={"SCP": {"S1"}})
        sync_runner._on_history_pre(None)
        self.assertEqual((len(sync_runner._PENDING), sync_runner._RUNNING), (0, False))

    def test_control_runtime_history_pre_skips_next_depsgraph_sync(self):
        runtime = control_runtime.register_control_runtime()
        runtime._last_active = ("SCP", "S1")
        with patch.object(runtime, "sync_now") as sync_now:
            control_runtime._on_history_pre(None)
            runtime.on_depsgraph_update(bpy.context.scene, None)
            runtime.on_depsgraph_update(bpy.context.scene, None)
        self.assertEqual((runtime._last_active, sync_now.call_count), (("NONE", ""), 1))

    def test_source_start_nodes_exclude_non_source_payload_ids(self):
        starts = {("SCP", "S1"), ("SCP", "S2"), ("FIBER", "F1")}
        meta = {"payload": {"non_source_ids_by_type": {"SCP": ["S2"]}}}
        self.assertEqual(runtime._source_start_nodes(starts, meta), {("SCP", "S1"), ("FIBER", "F1")})

    def test_normalize_dirty_hints_falls_back_to_full_when_no_ids_match(self):
        dirty, is_full = runtime._normalize_dirty_hints({"SCP": {"S1", "S2"}, "FIBER": {"F1"}}, {"SCP": {"MISS"}})
        self.assertTrue(is_full)
        self.assertEqual((dirty["SCP"], dirty["FIBER"]), ({"S1", "S2"}, {"F1"}))

    def test_dispatch_runtime_intent_enqueues_and_seeds_dirty_sync(self):
        root_obj = root()
        runtime_intents.pop_runtime_intents(root_obj)
        with patch("core.visualization.sync_runner.sync_from_dirty_hints") as sync:
            runtime_intents.dispatch_runtime_intent(root=root_obj, scene=bpy.context.scene, intent_type="SCP/RECAPTURE_ATTACHMENT", entity_type="SCP", entity_id="S1", source="property")
        queued = runtime_intents.pop_runtime_intents(root_obj)
        self.assertEqual((queued[0].intent_type, queued[0].entity_id), ("SCP/RECAPTURE_ATTACHMENT", "S1"))
        self.assertEqual(sync.call_args.kwargs["dirty_hints"]["SCP"], {"S1"})

    def test_dispatch_runtime_intent_resolves_root_from_scene_context(self):
        root_obj = root()
        runtime_intents.pop_runtime_intents(root_obj)
        with patch("core.visualization.sync_runner.sync_from_dirty_hints") as sync:
            runtime_intents.dispatch_runtime_intent(scene=bpy.context.scene, intent_type="SCP/RECAPTURE_ATTACHMENT", entity_type="SCP", entity_id="S1", source="property")
        queued = runtime_intents.pop_runtime_intents(root_obj)
        self.assertEqual((queued[0].intent_type, sync.call_args.kwargs["root"]), ("SCP/RECAPTURE_ATTACHMENT", root_obj))

    def test_apply_runtime_intent_recapture_returns_scp_impact(self):
        intent = runtime_intents.RuntimeIntent(intent_type="SCP/RECAPTURE_ATTACHMENT", entity_type="SCP", entity_id="S1")
        with patch("core.deps.runtime_intent_behaviors.recapture_attachment_for_scp", return_value=True):
            self.assertEqual(runtime_intent_behaviors.apply_runtime_intent(root(), bpy.context.scene, intent), {"SCP": {"S1"}})

    def test_dependency_runtime_gate_filters_sync_ids_and_still_runs_post_sync(self):
        calls, driver = [], RecorderDriver([])
        driver.calls = calls
        gate_map = {phase: [] for phase in gates._GATES}
        gate_map[gates.PHASE_PRE_SYNC] = [(0, lambda ctx: gates.GateDecision(filtered_ids={"S1"}))]
        with patch.object(drivers, "_DRIVERS", OrderedDict([(driver.name, driver)])), patch.object(gates, "_GATES", gate_map):
            runtime.run_dependency_runtime(SimpleNamespace(), SimpleNamespace(), {"SCP": {"S1", "S2"}})
        self.assertIn(("sync", False, {"S1"}), calls)
        self.assertIn(("post", {"S1", "S2"}), calls)

    def test_scp_sync_driver_skips_selection_events(self):
        driver = builtin_drivers.SCPSyncDriver()
        with patch.object(builtin_drivers, "_sync_scp_scene") as sync:
            driver.sync(root(), bpy.context.scene, False, {"SCP": {"S1"}}, False, gate_meta={"event_type": "SELECTION"})
        self.assertEqual(sync.call_count, 0)

    def test_fiber_sync_driver_refreshes_selection_without_geometry_sync(self):
        driver = builtin_drivers.FiberSyncDriver()
        sync = SimpleNamespace(refresh_selection=Mock(), sync_root_to_scene=Mock())
        with patch.object(builtin_drivers, "register_fiber_sync", return_value=sync):
            driver.sync(root(), bpy.context.scene, False, {"FIBER": {"F1"}}, False, gate_meta={"event_type": "SELECTION"})
        self.assertEqual((sync.refresh_selection.call_count, sync.sync_root_to_scene.call_count), (1, 0))
