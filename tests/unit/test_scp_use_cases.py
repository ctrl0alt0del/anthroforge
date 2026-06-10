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

from app.use_cases.scp_parenting import (
    _capture_parent_change,
    mark_active_mesh_as_scp,
    reparent_scp,
    set_active_scp_parent,
)


class Bag(dict):
    def __init__(self, **values):
        super().__init__(**values)
        self.__dict__ = self


class FakeSelectable(Bag):
    def __init__(self, name, **values):
        super().__init__(name=name, selected=False, **values)

    def select_set(self, value):
        self.selected = bool(value)


def root(scps=()):
    system = Bag(scps=list(scps), active_scp_index=0)
    return Bag(name="ROOT", anthroforge_root=True, af_scp_system=system)


def scene(*objects):
    return SimpleNamespace(objects=list(objects), af_scp_parent_obj=None)


def context(scene_obj, active_object=None, selected_objects=()):
    layer = SimpleNamespace(objects=SimpleNamespace(active=None))
    return SimpleNamespace(scene=scene_obj, active_object=active_object, selected_objects=list(selected_objects), view_layer=layer)


class ScpUseCaseTests(unittest.TestCase):
    def test_mark_active_mesh_as_scp_finalizes_mark_flow(self):
        root_obj = root()
        loose = FakeSelectable("Loose", type="MESH")
        ctx = context(scene(root_obj, loose), active_object=loose, selected_objects=[loose])
        scp = Bag(id="S1")
        with patch("app.use_cases.scp_parenting._create_marked_scp", return_value=scp):
            with patch("app.use_cases.scp_parenting._apply_optional_parent", return_value=(True, "")):
                with patch("app.use_cases.scp_parenting._finalize_mark") as finalize:
                    result = mark_active_mesh_as_scp(ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "Marked 'Loose' as S1")
        finalize.assert_called_once_with(ctx, root_obj, scp, loose)

    def test_mark_active_mesh_as_scp_rejects_existing_binding(self):
        root_obj = root()
        loose = FakeSelectable("Loose", type="MESH")
        ctx = context(scene(root_obj, loose), active_object=loose)
        with patch("app.use_cases.scp_parenting._scp_for_object", return_value=lambda *_args: object()):
            result = mark_active_mesh_as_scp(ctx)
        self.assertEqual((result.ok, result.message), (False, "Object already belongs to an SCP."))

    def test_set_active_scp_parent_syncs_updated_child(self):
        root_obj = root()
        child = (Bag(name="Child"), Bag(id="S1"))
        calls = []
        ctx = context(scene(root_obj))
        with patch("app.use_cases.scp_parenting._resolved_active_child", return_value=(child, "")):
            with patch("app.use_cases.scp_parenting._apply_parent_change", return_value=(True, "")):
                with patch("app.use_cases.scp_parenting._sync_entity", side_effect=lambda *args: calls.append(args)):
                    result = set_active_scp_parent(ctx)
        self.assertTrue(result.ok)
        self.assertEqual(calls[0][1], "S1")

    def test_reparent_scp_reports_missing_parent_transform(self):
        root_obj = root()
        child = (Bag(name="Child"), Bag(id="S1"))
        ctx = context(scene(root_obj))
        with patch("app.use_cases.scp_parenting._resolved_child_by_id", return_value=(child, "")):
            with patch("app.use_cases.scp_parenting._resolved_parent_by_id", return_value=(None, "Target parent SCP has no transform object.")):
                result = reparent_scp(ctx, "S1", "S2")
        self.assertEqual((result.ok, result.message), (False, "Target parent SCP has no transform object."))

    def test_capture_parent_change_restores_snapshot_on_failure(self):
        child_scp = Bag(id="S1", attach_child_anchor_mode="FACE_CENTER")
        child_obj = Bag(name="Child")
        parent_obj = Bag(name="Parent", af_scp_id="S2")
        ctx = context(scene())
        restored = []
        with patch("app.use_cases.scp_parenting._snapshot_link_state", return_value=lambda *_args: {"parent_id": ""}):
            with patch("app.use_cases.scp_parenting._attachment_geometry", return_value=(None, None)):
                with patch("app.use_cases.scp_parenting._set_parent_relation", return_value=lambda *_args: None):
                    with patch("app.use_cases.scp_parenting._capture_attachment", return_value=lambda *_args: False):
                        with patch("app.use_cases.scp_parenting._restore_link_state", return_value=lambda *_args: restored.append(True)):
                            result = _capture_parent_change(ctx, "ROOT", child_obj, child_scp, parent_obj)
        self.assertEqual(result, (False, "Failed to capture attachment."))
        self.assertEqual(restored, [True])


if __name__ == "__main__":
    unittest.main()
