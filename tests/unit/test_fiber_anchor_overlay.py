from pathlib import Path
import sys
import types
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

from core.vcp import fiber_anchor_preflight as preflight
from core.visualization import fiber_anchor_overlay as overlay


class Space:
    added = []
    removed = []

    @classmethod
    def draw_handler_add(cls, *args):
        cls.added.append(args)
        return "handler"

    @classmethod
    def draw_handler_remove(cls, *args):
        cls.removed.append(args)


def gpu_module():
    state = SimpleNamespace(blend_get=lambda: "MULTIPLY", depth_test_get=lambda: "GREATER",
                            blend_set=Mock(), depth_test_set=Mock())
    return SimpleNamespace(state=state)


class FiberAnchorOverlayTests(unittest.TestCase):
    def setUp(self):
        overlay._BATCHES.clear()
        overlay._HANDLER, overlay._SHADER = None, None
        Space.added.clear(); Space.removed.clear()

    def test_draw_uses_only_cached_batch_and_restores_gpu_state(self):
        gpu, batch = gpu_module(), object()
        with patch.dict(sys.modules, {"gpu": gpu}), patch.object(overlay, "_active_batch", return_value=batch), \
             patch.object(overlay, "_draw_batch") as draw, \
             patch.object(preflight.CollisionOracle, "colliders", side_effect=AssertionError("geometry queried")):
            overlay._draw_invalid_anchors()
        draw.assert_called_once_with(gpu, batch)
        gpu.state.blend_set.assert_called_once_with("MULTIPLY")
        gpu.state.depth_test_set.assert_called_once_with("GREATER")

    def test_selection_switching_fetches_only_active_scope(self):
        first, second = ("scope", 1), ("scope", 2)
        overlay._BATCHES[first] = ("key", "first-batch")
        overlay._BATCHES[second] = ("key", "second-batch")
        with patch.object(overlay, "_active_scope", side_effect=(first, second)):
            self.assertEqual(overlay._active_batch(), "first-batch")
            self.assertEqual(overlay._active_batch(), "second-batch")

    def test_same_result_reuses_cached_gpu_batch(self):
        batch_for_shader = Mock(return_value="batch")
        module = types.ModuleType("gpu_extras.batch"); module.batch_for_shader = batch_for_shader
        result = SimpleNamespace(cache_key=("key",), violations=(SimpleNamespace(point=(1, 2, 3)),))
        with patch.dict(sys.modules, {"gpu_extras.batch": module}), patch.object(overlay, "_shader", return_value="shader"):
            overlay.cache_fiber_anchor_overlay("scope", result)
            overlay.cache_fiber_anchor_overlay("scope", result)
        batch_for_shader.assert_called_once()

    def test_register_unregister_is_idempotent_and_clears_batches(self):
        overlay.bpy.types = SimpleNamespace(SpaceView3D=Space)
        with patch.object(overlay, "_shader", return_value="shader"):
            overlay.register_fiber_anchor_overlay(lambda: None)
            overlay.register_fiber_anchor_overlay(lambda: None)
            overlay._BATCHES["scope"] = ("key", "batch")
            overlay.unregister_fiber_anchor_overlay()
        self.assertEqual((len(Space.added), len(Space.removed)), (1, 1))
        self.assertFalse(overlay._BATCHES)


if __name__ == "__main__":
    unittest.main()
