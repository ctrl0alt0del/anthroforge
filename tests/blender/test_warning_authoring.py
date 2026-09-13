"""Live feedback outside cached responses and native authoring capture."""
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from test_fiber_anchor_preflight import _scene_fixture
from test_warning_repository import drain, check_all, query_api, forbid_solves
from anthroforge.core.authoring.reports import response
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.storage import FileStore
from anthroforge.app.authoring.facade import AuthoringInterpreter
from anthroforge.adapters.authoring.warnings import BlenderWarnings
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def mutation_request(owner_root):
    return dict(version="0.4.0", message_type="request", request_id="create-midpoint", op="anatomy.initialize",
                params=dict(scene_id=owner_root.name, expected_scene_revision="known"))


def service(owner_root, directory):
    return AuthoringInterpreter(None, None, FileStore(directory), warnings=BlenderWarnings(owner_root, bpy.context.scene))


class WarningAuthoringTests(BlenderTestCase):
    def test_invalid_midpoint_feedback_correction_poll_and_live_cached_replay(self):
        owner_root, blocker, _owner, fiber = _scene_fixture(); request = mutation_request(owner_root)
        with TemporaryDirectory() as directory:
            interpreter = service(owner_root, directory); cached = response(request)
            with patch.object(interpreter, "_execute", return_value=cached):
                pending = interpreter.execute(request)
            self.assertFalse(pending["warnings"]["complete"]); self.assertNotIn("warnings", cached)
            drain(); found = query_api(owner_root, directory)["warnings"]
            self.assertEqual(found["total"], 2)
            self.assertIn("TOUCH", {row["pin"]["role"] for row in found["records"]})
            blocker.location.x = 10; bpy.context.view_layer.update(); drain()
            with patch.object(interpreter, "_execute", return_value=dict(cached, replayed=True)):
                replay = interpreter.execute(request)
            self.assertEqual(replay["warnings"]["total"], 0); self.assertTrue(replay["warnings"]["complete"])
            self.assertNotEqual(pending["warnings"]["check_token"], replay["warnings"]["check_token"])

    def test_partial_failed_mutation_keeps_status_and_exposes_pending_validation(self):
        owner_root, _blocker, _owner, fiber = _scene_fixture(); request = mutation_request(owner_root)
        with TemporaryDirectory() as directory:
            interpreter = service(owner_root, directory)
            failed = dict(response(request), status="failed", diagnostics=[dict(code="TEST_FAILURE")])
            with patch.object(interpreter, "_execute", return_value=failed):
                value = interpreter.execute(request)
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["diagnostics"], failed["diagnostics"])
            self.assertFalse(value["warnings"]["complete"])
            self.assertNotIn("warnings", failed)

    def test_real_query_schema_and_no_geometry_or_solver_work(self):
        owner_root, _blocker, _owner, _fiber = _scene_fixture(); check_all()
        with TemporaryDirectory() as directory, forbid_solves():
            value = query_api(owner_root, directory, entity="FIBER_PREFLIGHT", limit=1)
        validate(value, "protocol")
        self.assertEqual(value["warnings"]["total"], 2)
        self.assertEqual(len(value["warnings"]["records"]), 1)

    def test_visual_selection_feedback_does_not_invalidate(self):
        from anthroforge.core.warnings import session
        owner_root, _blocker, _owner, _fiber = _scene_fixture(); check_all()
        revision = session.REPOSITORY.revision
        value = BlenderWarnings(owner_root, bpy.context.scene).feedback(dict(op="anatomy.select_region"), dict(status="success"))
        self.assertTrue(value["warnings"]["complete"])
        self.assertEqual(session.REPOSITORY.revision, revision)
        self.assertFalse(session.COORDINATOR.jobs)
