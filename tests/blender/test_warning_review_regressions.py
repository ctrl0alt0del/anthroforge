"""Real lifecycle/query boundaries for the AF-20 independent-review regressions."""
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from test_fiber_anchor_preflight import _scene_fixture, _fiber_with_touch
from test_warning_repository import check_all, drain, forbid_solves, query_api
from anthroforge.core.warnings import anchors, session
from anthroforge.core.visualization import warning_runtime as runtime
from anthroforge.core.visualization import fiber_anchor_overlay as overlay
from anthroforge.core.visualization.delete_reconcile import reconcile_deleted_entities, cleanup_scp_dependents
from anthroforge.core.visualization.fiber_cache_lifecycle import invalidate_fiber_caches
from anthroforge.core.vcp.fiber_anchor_preflight import current_fiber_anchor_preflight
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def filtered_query(owner_root, fiber_id):
    with TemporaryDirectory() as directory:
        return query_api(owner_root, directory, scene=session.id_token(bpy.context.scene),
                         root=session.id_token(owner_root), entity=fiber_id, kind="FIBER")["warnings"]


def remove_owner(owner_root, owner):
    index = next(i for i, row in enumerate(owner_root.af_scp_system.scps) if row.id == owner.id)
    owner_root.af_scp_system.scps.remove(index)


def queue_retired(owner_root, fiber_id):
    runtime.structural_change(owner_root, {fiber_id})
    runtime.notify_action(owner_root, bpy.context.scene, {"FIBER": {fiber_id}})


class WarningReviewRegressionTests(BlenderTestCase):
    def test_full_cache_invalidation_normalizes_null_and_absent_dirty(self):
        owner_root, _blocker, _owner, _fiber = _scene_fixture(); check_all()
        with forbid_solves():
            invalidate_fiber_caches(scene=bpy.context.scene, root=owner_root)
            self.assertTrue(session.COORDINATOR.jobs); drain()
            runtime.InvalidAnchorProvider().on_action({}, (bpy.context.scene, owner_root))
            self.assertTrue(session.COORDINATOR.jobs); drain()
        self.assertTrue(filtered_query(owner_root, "FIBER_PREFLIGHT")["complete"])

    def test_actual_fiber_delete_reconciles_and_invalidates_cache(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        fiber_id = str(fiber.id)
        with forbid_solves():
            changed = reconcile_deleted_entities(owner_root, bpy.context.scene, {("FIBER", fiber_id, "PROXY")})
            self.assertTrue(changed); self.assertEqual(len(owner_root.af_vcp_system.fibers), 0)
            self.assertFalse(filtered_query(owner_root, fiber_id)["complete"]); drain()
        result = filtered_query(owner_root, fiber_id)
        self.assertEqual(result["total"], 0); self.assertTrue(result["complete"], result)

    def test_actual_scp_delete_reconciles_dependent_fiber(self):
        owner_root, _blocker, owner, fiber = _scene_fixture(); check_all()
        owner_id, fiber_id = str(owner.id), str(fiber.id)
        with forbid_solves(), suppress_vcp_prop_updates():
            remove_owner(owner_root, owner)
            changed = reconcile_deleted_entities(owner_root, bpy.context.scene, {("SCP", owner_id, "GEOMETRY")})
            self.assertTrue(changed); self.assertEqual(len(owner_root.af_vcp_system.fibers), 0); drain()
        result = filtered_query(owner_root, fiber_id)
        self.assertEqual(result["total"], 0); self.assertTrue(result["complete"], result)

    def test_scp_dependency_cleanup_invalidates_cache_without_dirty_hint(self):
        owner_root, _blocker, owner, fiber = _scene_fixture(); check_all()
        fiber_id = str(fiber.id)
        with forbid_solves(), suppress_vcp_prop_updates():
            remove_owner(owner_root, owner)
            self.assertTrue(cleanup_scp_dependents(owner_root)); drain()
        self.assertEqual(len(owner_root.af_vcp_system.fibers), 0)
        self.assertEqual(filtered_query(owner_root, fiber_id)["total"], 0)

    def test_filtered_retired_entity_query_reports_queued_root(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        queue_retired(owner_root, fiber.id)
        result = filtered_query(owner_root, fiber.id)
        self.assertEqual(result["total"], 0)
        self.assert_pending_root(result, owner_root)
        with forbid_solves():
            drain()
        self.assertEqual(filtered_query(owner_root, fiber.id)["total"], 2)

    def test_filtered_new_entity_query_reports_queued_root(self):
        owner_root, _blocker, owner, _fiber = _scene_fixture(); check_all()
        with suppress_vcp_prop_updates():
            new = _fiber_with_touch(owner_root, owner, owner_root.af_scp_system.scps[2])
            new.id = "NEW_FIBER"
        runtime.notify_action(owner_root, bpy.context.scene, {"FIBER": {new.id}})
        result = filtered_query(owner_root, new.id)
        self.assertEqual(result["total"], 0); self.assert_pending_root(result, owner_root)
        with forbid_solves():
            drain()
        result = filtered_query(owner_root, new.id)
        self.assertEqual(result["total"], 2); self.assertTrue(result["complete"], result)

    def test_filtered_entity_query_reports_failed_root_capture(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        queue_retired(owner_root, fiber.id)
        with patch.object(runtime.capture, "capture_root", side_effect=RuntimeError("root capture unavailable")):
            drain()
        result = filtered_query(owner_root, fiber.id)
        self.assertEqual(result["total"], 0); self.assertFalse(result["complete"], result)
        self.assertEqual(result["counts"]["FAILED"], 1)
        self.assertEqual(result["failures"][0]["error"], "root capture unavailable")
        self.assertEqual(tuple(result["source_generations"][0]["scope"]), runtime.root_scope(bpy.context.scene, owner_root))

    def assert_pending_root(self, result, owner_root):
        self.assertFalse(result["complete"], result)
        self.assertEqual(result["counts"]["PENDING"], 1)
        self.assertEqual(tuple(result["source_generations"][0]["scope"]), runtime.root_scope(bpy.context.scene, owner_root))

    def test_other_provider_warning_preserves_compatibility_and_overlay(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        row = next(iter(session.REPOSITORY.records.values()))
        with patch.object(overlay, "_shader", return_value="shader"), patch("gpu_extras.batch.batch_for_shader", return_value="batch"):
            overlay._repository_changed(session.REPOSITORY)
            self.assertIn(row.entity.scope, overlay._BATCHES)
            with self.assertNoLogs("anthroforge.core.warnings.repository", level="ERROR"):
                session.REPOSITORY.upsert(replace(row, provider="other.v1", code="GENERAL", pin=None, evidence=()))
            self.assertIn(row.entity.scope, overlay._BATCHES)
            actual = current_fiber_anchor_preflight(bpy.context.scene, owner_root, fiber)
        self.assertEqual(len(actual.violations), 2)
        self.assertEqual(filtered_query(owner_root, fiber.id)["total"], 3)

    def test_compatibility_requires_anchor_provider_and_code(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); check_all()
        row = next(iter(session.REPOSITORY.records.values())); repo = session.REPOSITORY
        metadata = repo.metadata[row.entity.scope, anchors.PROVIDER]
        rows = [repo.records[key] for key in repo.scopes[row.entity.scope]]
        with self.assertNoLogs("anthroforge.core.warnings.repository", level="ERROR"):
            repo.replace(row.entity.scope, [*rows, replace(row, code="GENERAL", pin=None, evidence=())], metadata=metadata)
            repo.upsert(replace(row, provider="other.v1", pin=None, evidence=()))
            actual = current_fiber_anchor_preflight(bpy.context.scene, owner_root, fiber)
        self.assertEqual(len(actual.violations), 2)
        self.assertEqual(filtered_query(owner_root, fiber.id)["total"], 4)
