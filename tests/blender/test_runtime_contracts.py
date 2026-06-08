from pathlib import Path
from collections import OrderedDict
from types import SimpleNamespace
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, root, scp_with_object
from core.deps.drivers import DependencyDriver
from core.visualization.scp_control_helpers import mark_scp_control_object
from core.visualization import control_runtime, delete_reconcile, sync_runner
from core.deps import drivers, gates, runtime, runtime_intent_behaviors, runtime_intents


def _restore_addon():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()


def _handler_count(seq, fn):
    return sum(item is fn for item in tuple(seq))


def _reset_sync_runner():
    sync_runner._RUNNING = False
    sync_runner._TIMER_ARMED = False
    sync_runner._PENDING.clear()


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
        self.addCleanup(_restore_addon)
        anthroforge.unregister()
        self.assertFalse(hasattr(bpy.types.Object, "af_scp_system"))
        anthroforge.register()
        self.assertTrue(hasattr(bpy.types.Object, "af_scp_system"))
        self.assertEqual(_handler_count(bpy.app.handlers.load_post, control_runtime._on_load_post), 1)
        self.assertEqual(_handler_count(bpy.app.handlers.load_post, delete_reconcile._on_load_post), 1)

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
