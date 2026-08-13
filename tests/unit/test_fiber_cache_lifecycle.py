from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
install_fake_modules()

from app.use_cases import fiber_create
from core import utils
from core.deps import runtime_context_build
from core.vcp.fiber_solver_v2 import DEFAULT_FACTOR_CACHE, factor_cache_stats
from core.visualization import delete_reconcile, fiber_cache_lifecycle as lifecycle


class Bag(dict):
    def __init__(self, **values):
        super().__init__(**values)
        self.__dict__ = self


class FiberCollection(list):
    def add(self):
        item = Bag(mid_touches=FiberCollection(), loop_anchors=FiberCollection())
        self.append(item)
        return item


class Pointer:
    def __init__(self, value):
        self.value = value

    def as_pointer(self):
        return self.value


class FiberCacheLifecycleTests(unittest.TestCase):
    def setUp(self):
        handlers = lifecycle.bpy.app.handlers
        handlers.undo_post = getattr(handlers, "undo_post", [])
        handlers.redo_post = getattr(handlers, "redo_post", [])

    def tearDown(self):
        for handlers in lifecycle._handler_lists():
            while lifecycle._on_lifecycle_event in handlers:
                handlers.remove(lifecycle._on_lifecycle_event)

    def test_invalidation_dispatches_every_cache_layer(self):
        scene, root = object(), object()
        targets = ("_cancel_refinements", "_clear_solver_cache", "clear_factor_cache",
                   "clear_runtime_context_cache", "clear_scene_cache", "clear_geometry_generations")
        patches = [patch.object(lifecycle, name) for name in targets]
        mocks = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in patches])
        lifecycle.invalidate_fiber_caches(scene, root)
        self.assertEqual([mock.call_count for mock in mocks], [1] * len(mocks))

    def test_full_invalidation_clears_real_global_caches(self):
        scene, root = Pointer(41), Pointer(42)
        utils.scene_cache_set(scene, "('fiber_spatial_index',)", "stale")
        runtime_context_build._GRAPH_CACHE[root.as_pointer()] = {"stale": True}
        DEFAULT_FACTOR_CACHE._entries["stale"] = SimpleNamespace(nbytes=1)
        DEFAULT_FACTOR_CACHE._bytes = 1
        with patch.object(lifecycle, "_cancel_refinements"), patch.object(lifecycle, "_clear_solver_cache"):
            lifecycle.invalidate_fiber_caches(scene, root)
        self.assertIsNone(utils.scene_cache_get(scene, "('fiber_spatial_index',)"))
        self.assertNotIn(root.as_pointer(), runtime_context_build._GRAPH_CACHE)
        self.assertEqual(factor_cache_stats()["entries"], 0)

    def test_lifecycle_registration_is_idempotent_and_unregistered(self):
        lifecycle.register_fiber_cache_lifecycle()
        lifecycle.register_fiber_cache_lifecycle()
        self.assertTrue(all(seq.count(lifecycle._on_lifecycle_event) == 1 for seq in lifecycle._handler_lists()))
        with patch.object(lifecycle, "invalidate_fiber_caches") as invalidate:
            lifecycle.unregister_fiber_cache_lifecycle()
        self.assertEqual(invalidate.call_count, 1)
        self.assertTrue(all(lifecycle._on_lifecycle_event not in seq for seq in lifecycle._handler_lists()))

    def test_load_or_history_handler_invalidates_all(self):
        with patch.object(lifecycle, "invalidate_fiber_caches") as invalidate:
            lifecycle._on_lifecycle_event(None)
        invalidate.assert_called_once_with()

    def test_depsgraph_handler_tracks_surface_geometry(self):
        depsgraph = object()
        with patch.object(lifecycle, "note_geometry_updates") as surface:
            with patch.object(lifecycle, "note_collider_updates") as collider:
                lifecycle._on_depsgraph_update(None, depsgraph)
        surface.assert_called_once_with(depsgraph)
        collider.assert_called_once_with(depsgraph)

    def test_new_fiber_invalidates_reused_identifier(self):
        root = SimpleNamespace(af_vcp_system=SimpleNamespace(fibers=FiberCollection()))
        with patch.object(fiber_create, "_invalidate_fiber_runtime") as invalidate:
            fiber = fiber_create._new_fiber(root, "A", "B", "a", "b")
        invalidate.assert_called_once_with(root, fiber.id)

    def test_reconcile_invalidates_after_deletion(self):
        root, scene = object(), object()
        with patch.object(delete_reconcile, "_reconcile_removed", return_value=True):
            with patch.object(delete_reconcile, "invalidate_fiber_caches") as invalidate:
                changed = delete_reconcile.reconcile_deleted_entities(root, scene, {("FIBER", "F1", "PROXY")})
        self.assertTrue(changed)
        invalidate.assert_called_once_with(scene=scene, root=root)


if __name__ == "__main__":
    unittest.main()
