from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, root
from core.deps.control_behaviors import apply_control_intent, register_control_handler
from core.deps.controls import ControlIntent


class FakeExt:
    def __init__(self, sid):
        self.sid = sid

    def handle_object_update(self, *_args, **_kwargs):
        return True, True, self.sid


class FakeSync:
    collection_name = "AF_TEST_VIS"

    def __init__(self, sid):
        self._shape_sync_extensions = [FakeExt(sid)]


def _ensure_vis_collection():
    return bpy.data.collections.get("AF_TEST_VIS") or bpy.data.collections.new("AF_TEST_VIS")


class ControlIntentRoutingTests(BlenderTestCase):
    def test_apply_control_intent_routes_scp_shape_controls(self):
        root_obj = root()
        ctrl = empty_object("CTRL")
        _ensure_vis_collection()
        intent = ControlIntent("SCP_CURVE_POINT", {"object_name": ctrl.name, "binding": {"kind": "POINT"}})
        with patch("core.deps.control_behaviors.register_sync", return_value=FakeSync("S1")):
            self.assertEqual(apply_control_intent(root_obj, bpy.context.scene, intent), {"SCP": {"S1"}})

    def test_apply_control_intent_routes_direct_scp_controls(self):
        intent = ControlIntent("SCP_CONTROL_OBJECT", {"scp_id": "S1"})
        self.assertEqual(apply_control_intent(root(), bpy.context.scene, intent), {"SCP": {"S1"}})

    def test_apply_control_intent_routes_fiber_controls(self):
        root_obj = root()
        ctrl = empty_object("CTRL")
        intent = ControlIntent("FIBER_ENDPOINT", {"object_name": ctrl.name})
        with patch("core.deps.control_behaviors.apply_fiber_control_update", return_value="F1"):
            self.assertEqual(apply_control_intent(root_obj, bpy.context.scene, intent), {"FIBER": {"F1"}})

    def test_apply_control_intent_routes_muscle_and_blob_controls(self):
        root_obj = root()
        muscle = empty_object("MUSCLE_CTRL")
        blob = empty_object("BLOB_CTRL")
        with patch("core.deps.control_behaviors.apply_muscle_control_update", return_value="M1"):
            out = apply_control_intent(root_obj, bpy.context.scene, ControlIntent("MUSCLE_INFLATION", {"object_name": muscle.name}))
        with patch("core.deps.control_behaviors.apply_blob_control_update", return_value="B1"):
            blob_out = apply_control_intent(root_obj, bpy.context.scene, ControlIntent("BLOB_CONTROL", {"object_name": blob.name}))
        self.assertEqual((out, blob_out), ({"MUSCLE": {"M1"}}, {"BLOB": {"B1"}}))

    def test_registered_handler_extends_control_routing(self):
        register_control_handler("CUSTOM_CONTROL", _custom_handler, replace=True)
        out = apply_control_intent(root(), bpy.context.scene, ControlIntent("CUSTOM_CONTROL", {"scp_id": "S9"}))
        self.assertEqual(out, {"SCP": {"S9"}})


def _custom_handler(_root, _scene, intent):
    return {"SCP": {str(intent.payload.get("scp_id") or "")}}
