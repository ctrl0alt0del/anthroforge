from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy
from _helpers import BlenderTestCase, fiber, mesh_object, root, scp_with_object
from core.deps.runtime_trace import clear_request_telemetry, request_telemetry, set_request_telemetry
from core.visualization import sync_runner
from core.visualization.fiber_sync import register_fiber_sync


class ScpSyncAmplificationTests(BlenderTestCase):
    def tearDown(self):
        set_request_telemetry(False)
        clear_request_telemetry()
        sync_runner.clear_pending_runtime(keep_timer=False)

    def test_one_scp_request_solves_each_affected_fiber_once_without_property_tail(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Source", mesh_object("Source"))
        target = scp_with_object(root_obj, "Target", mesh_object("Target"))
        fibers = [fiber(root_obj, source.id, target.id) for _index in range(2)]
        sync, payload = register_fiber_sync(), {"scp_apply_target_ids": [source.id]}
        sync_runner.clear_pending_runtime(keep_timer=False)
        set_request_telemetry(True); clear_request_telemetry()
        with patch("core.visualization.fiber_refinement.request_fiber_refinement") as request:
            sync_runner.sync_from_dirty_hints(root_obj, bpy.context.scene, {"SCP": {source.id}},
                                              source="depsgraph", event_type="SCP_UPDATE", payload=payload, full=False)
        requested = [call.args[2].id for call in request.call_args_list]
        sources = [record["source"] for record in request_telemetry()]
        self.assertEqual((requested, sources, len(sync_runner._TAIL_PENDING)),
                         ([item.id for item in fibers], ["depsgraph"], 0))
