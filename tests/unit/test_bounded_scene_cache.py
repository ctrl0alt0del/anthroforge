from pathlib import Path
import sys
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from core import utils


class Pointer:
    def __init__(self, value, session_uid=0):
        self.value, self.session_uid = value, session_uid

    def as_pointer(self):
        return self.value


class BoundedSceneCacheTests(unittest.TestCase):
    def setUp(self):
        utils.clear_scene_cache()

    def tearDown(self):
        utils.clear_scene_cache()

    def test_entry_limit_evicts_least_recently_used(self):
        scene = Pointer(1)
        self._set(scene, "a", 1, max_entries=2)
        self._set(scene, "b", 2, max_entries=2)
        self.assertEqual(utils.bounded_scene_cache_get(scene, "a", "test"), 1)
        self._set(scene, "c", 3, max_entries=2)
        self.assertIsNone(utils.scene_cache_get(scene, "b"))
        self.assertEqual((utils.scene_cache_get(scene, "a"), utils.scene_cache_get(scene, "c")), (1, 3))

    def test_byte_limit_accounts_and_evicts(self):
        scene = Pointer(2)
        self._set(scene, "a", object(), max_bytes=10, size_bytes=6)
        self._set(scene, "b", object(), max_bytes=10, size_bytes=6)
        stats = utils.bounded_scene_cache_stats("test")
        self.assertEqual((stats["entries"], stats["bytes"]), (1, 6))
        self.assertIsNone(utils.scene_cache_get(scene, "a"))

    def test_limit_is_global_across_scenes(self):
        first, second = Pointer(3), Pointer(4)
        self._set(first, "a", 1, max_entries=1)
        self._set(second, "b", 2, max_entries=1)
        self.assertIsNone(utils.scene_cache_get(first, "a"))
        self.assertEqual(utils.scene_cache_get(second, "b"), 2)

    def test_clear_scene_removes_entries_and_accounting(self):
        first, second = Pointer(5), Pointer(6)
        self._set(first, "fiber:a", 1)
        self._set(second, "fiber:b", 2)
        utils.clear_scene_cache(first)
        stats = utils.bounded_scene_cache_stats("test")
        self.assertEqual((stats["entries"], stats["bytes"]), (1, 1))

    def test_generic_cache_is_not_admitted_or_evicted(self):
        scene = Pointer(7)
        for index in range(200):
            utils.scene_cache_set(scene, f"generic:{index}", index)
        self.assertEqual(utils.bounded_scene_cache_stats()["entries"], 0)
        self.assertEqual(utils.scene_cache_get(scene, "generic:0"), 0)

    def test_adopt_moves_existing_entry_under_budget(self):
        scene = Pointer(8)
        utils.scene_cache_set(scene, "surface:full:1", {"mesh": True})
        value = utils.bounded_scene_cache_adopt(
            scene, "surface:full:1", "test", max_entries=1, max_bytes=10, size_bytes=4)
        self.assertEqual(value, {"mesh": True})
        self.assertEqual(utils.bounded_scene_cache_stats("test")["bytes"], 4)

    def test_session_uid_prevents_pointer_reuse(self):
        expired, replacement = Pointer(9, 101), Pointer(9, 102)
        utils.scene_cache_set(expired, "surface", "stale")
        self.assertIsNone(utils.scene_cache_get(replacement, "surface"))

    def _set(self, scene, key, value, max_entries=128, max_bytes=1024, size_bytes=1):
        return utils.bounded_scene_cache_set(
            scene, key, value, "test", max_entries=max_entries,
            max_bytes=max_bytes, size_bytes=size_bytes)


if __name__ == "__main__":
    unittest.main()
