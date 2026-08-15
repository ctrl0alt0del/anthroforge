from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _helpers import BlenderTestCase
from core.visualization import muscle_sync, sync_runner
from core.visualization.muscle_sync import register_muscle_sync


class MuscleFallbackFeedbackTests(BlenderTestCase):
    def test_active_runtime_does_not_recursively_request_missing_fibers(self):
        fibers = [SimpleNamespace(id="F1"), SimpleNamespace(id="F2")]
        with patch.object(muscle_sync, "collect_muscle_rows", return_value=[]), \
                patch.object(sync_runner, "runtime_request_active", return_value=True), \
                patch.object(sync_runner, "sync_from_dirty_hints") as nested:
            result = register_muscle_sync()._collect_points_with_fallback(
                object(), object(), object(), fibers)
        self.assertEqual(result, [])
        nested.assert_not_called()

    def test_direct_sync_retains_one_shot_legacy_fallback(self):
        fibers = [SimpleNamespace(id="F1")]; rows = [[(0.0, 0.0, 0.0)]]
        with patch.object(muscle_sync, "collect_muscle_rows", side_effect=[[], rows]), \
                patch.object(sync_runner, "runtime_request_active", return_value=False), \
                patch.object(sync_runner, "sync_from_dirty_hints") as nested:
            result = register_muscle_sync()._collect_points_with_fallback(
                object(), object(), object(), fibers)
        self.assertEqual(result, rows)
        nested.assert_called_once()
