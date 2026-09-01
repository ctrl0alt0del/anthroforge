from pathlib import Path
import sys
from types import SimpleNamespace
import os
from unittest.mock import Mock, patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT.parent)):
    if value not in sys.path: sys.path.insert(0, value)

from anthroforge.core.visualization import fiber_refinement
from _helpers import BlenderTestCase


class FiberV3BatchRuntimeTests(BlenderTestCase):
    def tearDown(self):
        fiber_refinement._GROUPS.clear()
        super().tearDown()

    def test_two_commits_publish_one_grouped_event(self):
        root = SimpleNamespace(session_uid=11); scene = SimpleNamespace(session_uid=12)
        rows = [(root, scene, SimpleNamespace(id="FIBER_2")),
                (root, scene, SimpleNamespace(id="FIBER_1"))]
        callback = Mock()
        with patch.object(fiber_refinement, "_owned_job_data", side_effect=rows), \
             patch.object(fiber_refinement, "_sync_scene", return_value=callback):
            fiber_refinement._begin_batch_publication()
            fiber_refinement._sync_final(object()); fiber_refinement._sync_final(object())
            fiber_refinement._end_batch_publication()
        callback.assert_called_once()
        self.assertEqual(callback.call_args.kwargs["payload"]["solved_fiber_ids"],
                         ["FIBER_1", "FIBER_2"])

    def test_detach_unregisters_v3_session(self):
        key = (1, 2, "FIBER_1")
        session = SimpleNamespace(engine="V3", done=False)
        job = SimpleNamespace(key=key, session=session)
        fiber_refinement._JOBS[key] = job; fiber_refinement._QUEUE.append(key)
        with patch.object(fiber_refinement, "_job_priority", return_value=1):
            fiber_refinement._register_batch_job(job)
        fiber_refinement._detach_job(job)
        self.assertNotIn(key, fiber_refinement._V3_BATCH.entries)
        self.assertNotIn(key, fiber_refinement._QUEUE)

    def test_auto_activation_requires_size_or_four_sessions(self):
        session = SimpleNamespace(engine="V3", done=False, params={"node_count": 64})
        job = SimpleNamespace(key="a", session=session)
        fiber_refinement._V3_BATCH.clear()
        with patch.dict(os.environ, {"AF_FIBER_V3_BATCH": "AUTO"}):
            for key in ("a", "b", "c"): fiber_refinement._V3_BATCH.add(key, session)
            self.assertFalse(fiber_refinement._batch_job_enabled(job))
            fiber_refinement._V3_BATCH.add("d", session)
            self.assertTrue(fiber_refinement._batch_job_enabled(job))
            session.params["node_count"] = 256
            self.assertTrue(fiber_refinement._batch_job_enabled(job))
        fiber_refinement._V3_BATCH.clear()

    def test_recompute_group_publishes_once_after_every_terminal_member(self):
        root = SimpleNamespace(session_uid=21, name="Root")
        scene = SimpleNamespace(session_uid=22, name="Scene")
        group = fiber_refinement._new_refinement_group(root, scene, ("FIBER_1", "FIBER_2"))
        with patch.object(fiber_refinement, "_group_data", return_value=(root, scene)), \
             patch.object(fiber_refinement, "_sync_fiber_group") as publish:
            fiber_refinement._group_member_done(group.token, "FIBER_1", True, "CONVERGED")
            publish.assert_not_called()
            fiber_refinement._group_member_done(group.token, "FIBER_2", False, "INVALID_ATTACHMENT")
        publish.assert_called_once_with(root, scene, {"FIBER_1"})

    def test_recompute_group_reports_success_and_failure_counts(self):
        root = SimpleNamespace(session_uid=31, name="Root")
        scene = SimpleNamespace(session_uid=32, name="Scene")
        group = fiber_refinement._new_refinement_group(root, scene, ("A", "B"))
        with patch.object(fiber_refinement, "_group_data", return_value=(None, None)):
            fiber_refinement._group_member_done(group.token, "A", True, "CONVERGED")
            fiber_refinement._group_member_done(group.token, "B", False, "BLOCKED")
        state = fiber_refinement.fiber_refinement_group_state(group.token)
        self.assertEqual((state["done"], state["committed"], state["failures"]),
                         (True, ("A",), {"B": "BLOCKED"}))


if __name__ == "__main__":
    import unittest
    unittest.main(argv=[__file__])
