from pathlib import Path
import importlib.util
import sys
import types
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

PKG = types.ModuleType("deps_controls_test")
PKG.__path__ = [str(ADDON_ROOT / "core" / "deps")]
sys.modules.setdefault("deps_controls_test", PKG)
stub = types.ModuleType("deps_controls_test.runtime_intents")
stub.enqueue_runtime_intent = lambda **_kwargs: True
sys.modules.setdefault("deps_controls_test.runtime_intents", stub)


def _load_controls():
    path = ADDON_ROOT / "core" / "deps" / "controls.py"
    spec = importlib.util.spec_from_file_location("deps_controls_test.controls", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


controls = _load_controls()
classify_control_object = controls.classify_control_object
ControlDescriptor = controls.ControlDescriptor
register_control_descriptor = controls.register_control_descriptor


class FakeObject(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name


class ControlClassificationTests(unittest.TestCase):
    def test_classify_all_current_control_types(self):
        cases = _control_cases()
        for props, kind, etype, eid in cases:
            with self.subTest(kind=kind):
                info = classify_control_object(FakeObject("ctrl", af_root_name="ROOT", **props))
                self.assertEqual((info["control_type"], info["dirty_hints"][etype]), (kind, {eid}))

    def test_registered_descriptor_extends_classification(self):
        descriptor = ControlDescriptor("af_custom_ctrl", "CUSTOM_CONTROL", _custom_control_info)
        register_control_descriptor(descriptor, replace=True)
        info = classify_control_object(FakeObject("ctrl", af_root_name="ROOT", af_custom_ctrl=True))
        self.assertEqual((info["control_type"], info["dirty_hints"]["SCP"]), ("CUSTOM_CONTROL", {"SX"}))


def _control_cases():
    return [
        ({"af_scp_control": True, "af_scp_id": "S1"}, "SCP_CONTROL_OBJECT", "SCP", "S1"),
        ({"af_curve_point_handle": True, "af_scp_id": "S1", "af_curve_point_index": 2}, "SCP_CURVE_POINT", "SCP", "S1"),
        ({"af_parallelepiped_vert_handle": True, "af_scp_id": "S1", "af_parallelepiped_vert_index": 1}, "SCP_PARALLELEPIPED_VERTEX", "SCP", "S1"),
        ({"af_fiber_endpoint_handle": True, "af_fiber_id": "F1", "af_fiber_endpoint": "A"}, "FIBER_ENDPOINT", "FIBER", "F1"),
        ({"af_fiber_touch_handle": True, "af_fiber_id": "F1", "af_fiber_touch_index": 0}, "FIBER_TOUCH", "FIBER", "F1"),
        ({"af_fiber_loop_anchor_handle": True, "af_fiber_id": "F1", "af_fiber_loop_anchor_index": 2}, "FIBER_LOOP_ANCHOR", "FIBER", "F1"),
        ({"af_muscle_inflation_ctrl": True, "af_muscle_id": "M1"}, "MUSCLE_INFLATION", "MUSCLE", "M1"),
        ({"af_blob_control_gizmo": True, "af_blob_id": "B1"}, "BLOB_CONTROL", "BLOB", "B1"),
    ]


def _custom_control_info(obj, root_name):
    return {
        "control_type": "CUSTOM_CONTROL",
        "payload": {"root_name": root_name, "object_name": obj.name, "scp_id": "SX"},
        "dirty_hints": {"SCP": {"SX"}},
        "binding": None,
    }
