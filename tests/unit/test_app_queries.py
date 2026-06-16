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
bpy = install_fake_modules()

from app.queries.control_objects import control_panel_state
from app.queries.create import create_panel_state
from app.queries.root import has_root
from app.queries.shortcuts import shortcut_panel_state
from app.queries.tree import tree_panel_state
from app.queries.vcp import active_blob_from_context, active_fiber_from_context, active_muscle_from_context, blob_proxy_for_context
from app.use_cases.control_objects import mark_selected_control, toggle_control_parent
from app.use_cases.create_root import create_root_if_missing
from app.use_cases.shortcuts import add_shortcut_from_context, delete_shortcut_from_context
from app.use_cases.tree_state import toggle_scp_tree_node, toggle_vcp_tree_node
from core.visualization.control_object_shortcuts import axis_shortcut_path


class FakeObject(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name
        self.rna_type = SimpleNamespace(properties={})
        self.parent = None

    def path_resolve(self, _path):
        return self


def scp(sid, name=""):
    return SimpleNamespace(id=sid, name=name)


def fiber(fid):
    return SimpleNamespace(id=fid)


def muscle(mid):
    return SimpleNamespace(id=mid, name=mid)


def blob(bid):
    return SimpleNamespace(id=bid, name=bid)


def shortcut(sid, name, owner_type, owner_id, data_path, overrides=()):
    return SimpleNamespace(id=sid, name=name, owner_type=owner_type, owner_id=owner_id, data_path=data_path, overrides=list(overrides))


def override(target_scp_id, parent_mode="KEEP", child_mode="KEEP", follow_mode="KEEP", strategy="KEEP"):
    return SimpleNamespace(target_scp_id=target_scp_id, parent_anchor_mode=parent_mode, child_anchor_mode=child_mode, follow_rotation_mode=follow_mode, rotation_strategy=strategy)


def root(active_scp=0, active_type="NONE", active_id="", scps=(), fibers=(), muscles=(), blobs=(), shortcuts=()):
    obj = FakeObject("ROOT", anthroforge_root=True)
    obj.af_scp_system = SimpleNamespace(active_scp_index=active_scp, scps=list(scps))
    obj.af_vcp_system = SimpleNamespace(active_vcp_type=active_type, active_vcp_id=active_id, fibers=list(fibers), muscles=list(muscles), blobs=list(blobs))
    obj.af_shortcut_system = SimpleNamespace(shortcuts=list(shortcuts))
    return obj


def scene(*objects, shortcut_mode="SELECTED", picked_control=None):
    return SimpleNamespace(
        objects=list(objects),
        af_tree_collapsed_json="",
        af_vcp_tree_collapsed_json="",
        af_shortcut_view_mode=shortcut_mode,
        af_control_scp_obj=picked_control,
    )


def context(scene, active_object=None, selected_objects=()):
    return SimpleNamespace(scene=scene, active_object=active_object, selected_objects=list(selected_objects))


class FakeShortcutCollection(list):
    def add(self):
        item = SimpleNamespace(id="", name="", owner_type="", owner_id="", data_path="", overrides=[])
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)


class AppQueryTests(unittest.TestCase):
    def setUp(self):
        bpy.data.objects.clear()

    def test_create_panel_state_tracks_root_and_active_scp(self):
        root_obj = root(scps=[scp("S1", "Arm"), scp("S2", "Leg")])
        active = FakeObject("LegObj", af_scp_bound=True, af_root_name=root_obj.name, af_scp_id="S2")
        ctx = context(scene(root_obj, active), active_object=active)
        state = create_panel_state(ctx)
        self.assertTrue(has_root(ctx))
        self.assertEqual((state.root, state.active_scp.id), (root_obj, "S2"))

    def test_tree_panel_state_collects_selected_entity_ids(self):
        root_obj = root(active_scp=0, scps=[scp("S1"), scp("S2")])
        selected = [
            FakeObject("Scp", af_scp_bound=True, af_root_name=root_obj.name, af_scp_id="S2"),
            FakeObject("Mirror", af_scp_bound=True, af_scp_mirror=True, af_root_name=root_obj.name, af_scp_id="S9"),
            FakeObject("Fiber", af_fiber_proxy=True, af_root_name=root_obj.name, af_fiber_id="F1"),
            FakeObject("Muscle", af_muscle_proxy=True, af_root_name=root_obj.name, af_muscle_id="M1"),
            FakeObject("Blob", af_blob_proxy=True, af_root_name=root_obj.name, af_blob_id="B1"),
            FakeObject("Other", af_scp_bound=True, af_root_name="OTHER", af_scp_id="S3"),
        ]
        state = tree_panel_state(context(scene(root_obj, *selected), selected_objects=selected))
        self.assertEqual(state.active_scp_id, "S1")
        self.assertEqual(state.selection.scp_ids, frozenset({"S2"}))
        self.assertEqual(state.selection.fiber_ids, frozenset({"F1"}))
        self.assertEqual(state.selection.muscle_ids, frozenset({"M1"}))
        self.assertEqual(state.selection.blob_ids, frozenset({"B1"}))

    def test_active_vcp_queries_follow_current_tree_selection(self):
        fiber_obj = fiber("F1")
        muscle_obj = muscle("M1")
        blob_obj = blob("B1")
        fiber_root = root(active_type="FIBER", active_id="F1", fibers=[fiber_obj])
        muscle_root = root(active_type="MUSCLE", active_id="M1", muscles=[muscle_obj])
        blob_root = root(active_type="BLOB", active_id="B1", blobs=[blob_obj])
        self.assertIs(active_fiber_from_context(context(scene(fiber_root))), fiber_obj)
        self.assertIs(active_muscle_from_context(context(scene(muscle_root))), muscle_obj)
        self.assertIs(active_blob_from_context(context(scene(blob_root))), blob_obj)

    def test_blob_proxy_query_ignores_mirror_proxy(self):
        root_obj = root(active_type="BLOB", active_id="B1", blobs=[blob("B1")])
        mirror = FakeObject("BlobMirror", af_blob_proxy=True, af_blob_mirror_proxy=True, af_root_name=root_obj.name, af_blob_id="B1")
        real = FakeObject("BlobReal", af_blob_proxy=True, af_root_name=root_obj.name, af_blob_id="B1")
        ctx = context(scene(root_obj, mirror, real))
        self.assertIs(blob_proxy_for_context(ctx, active_blob_from_context(ctx)), real)

    def test_control_panel_state_reports_parent_and_axis_shortcuts(self):
        parent = FakeObject("Parent")
        ctrl = FakeObject("Ctrl", af_scp_control=True, af_root_name="ROOT", af_scp_id="S1")
        ctrl.parent = parent
        row = shortcut("K1", "Ctrl X", "SCP", "S1", axis_shortcut_path(ctrl, "X"))
        root_obj = root(scps=[SimpleNamespace(id="S1", transform_object_ref=parent)], shortcuts=[row])
        state = control_panel_state(context(scene(root_obj, parent, ctrl), active_object=ctrl))
        checks = {item.axis: item.checked for item in state.axis_states}
        self.assertTrue(state.is_control and state.apply_parent)
        self.assertEqual(checks, {"X": True, "Y": False, "Z": False})

    def test_shortcut_panel_state_filters_selected_owner_and_resolves_target(self):
        obj = FakeObject("bound", af_root_name="ROOT", af_scp_id="S1")
        obj.rna_type.properties["location"] = SimpleNamespace(type="FLOAT", array_length=3)
        bpy.data.objects[obj.name] = obj
        keep = shortcut("K1", "Keep", "SCP", "S1", 'af://object_rna/bound/location[1]')
        skip = shortcut("K2", "Skip", "BLOB", "B1", 'af://object_rna/bound/location[2]')
        root_obj = root(scps=[scp("S1")], shortcuts=[keep, skip])
        state = shortcut_panel_state(context(scene(root_obj, obj), active_object=obj))
        self.assertEqual([row.shortcut.id for row in state.rows], ["K1"])
        self.assertIs(state.rows[0].target.owner, obj)

    def test_shortcut_panel_state_marks_ancestor_override_rows(self):
        obj = FakeObject("bound", af_root_name="ROOT", af_scp_id="C1")
        obj.rna_type.properties["location"] = SimpleNamespace(type="FLOAT", array_length=3)
        bpy.data.objects[obj.name] = obj
        parent = scp("P1")
        child = SimpleNamespace(id="C1", name="Child", parent_id="P1")
        rows = [
            shortcut("K1", "Parent", "SCP", "P1", 'af://object_rna/bound/location[0]', overrides=[override("C1", "OBJECT_ORIGIN")]),
            shortcut("K2", "Self", "SCP", "C1", 'af://object_rna/bound/location[1]'),
            shortcut("K3", "Other", "SCP", "S9", 'af://object_rna/bound/location[2]'),
        ]
        root_obj = root(active_scp=1, scps=[parent, child], shortcuts=rows)
        state = shortcut_panel_state(context(scene(root_obj, obj, shortcut_mode="ALL"), active_object=obj))
        data = {row.shortcut.id: row for row in state.rows}
        self.assertEqual((data["K1"].owner_relation, data["K1"].show_override, data["K1"].has_override), ("ANCESTOR", True, True))
        self.assertEqual((data["K2"].owner_relation, data["K2"].show_override), ("SELF", False))
        self.assertEqual((data["K3"].owner_relation, data["K3"].show_override), ("UNRELATED", False))

    def test_create_root_use_case_syncs_only_when_missing(self):
        calls = []
        scene_obj = scene()
        create_fn = lambda _scene: "ROOT"
        sync_fn = lambda **kwargs: calls.append(kwargs)
        dirty_fn = lambda: {"full": True}
        self.assertEqual(create_root_if_missing(scene_obj, {}, create_fn, sync_fn, dirty_fn), "ROOT")
        self.assertEqual(calls[0]["dirty_hints"], {"full": True})
        self.assertIsNone(create_root_if_missing(scene_obj, {"AF_ROOT": object()}, create_fn, sync_fn, dirty_fn))

    def test_tree_state_use_cases_toggle_scene_flags(self):
        scn = scene()
        self.assertTrue(toggle_scp_tree_node(scn, "S1"))
        self.assertIn('"S1": true', scn.af_tree_collapsed_json)
        self.assertTrue(toggle_vcp_tree_node(scn, "MUSCLE:M1"))
        self.assertIn('"MUSCLE:M1": true', scn.af_vcp_tree_collapsed_json)

    def test_control_use_case_delegates_mark_and_parent_toggle(self):
        calls = []
        ctx = context(scene())
        service = SimpleNamespace(
            mark_selected_scp_control=lambda root, current: calls.append(("mark", root, current)) or (True, ""),
            control_apply_parent_state=lambda *_args: False,
            set_selected_control_parent_applied=lambda root, current, enabled: calls.append(("parent", root, current, enabled)) or (True, ""),
        )
        with patch("app.use_cases.control_objects._root_for_context", return_value="ROOT"):
            with patch("app.use_cases.control_objects._control_service", return_value=service):
                self.assertEqual(mark_selected_control(ctx), (True, ""))
                self.assertEqual(toggle_control_parent(ctx), (True, ""))
        self.assertEqual(calls, [("mark", "ROOT", ctx), ("parent", "ROOT", ctx, True)])

    def test_shortcut_use_case_adds_and_deletes_shortcut(self):
        obj = FakeObject("bound")
        obj.rna_type.properties["location"] = SimpleNamespace(type="FLOAT", array_length=3)
        bpy.data.objects[obj.name] = obj
        entry = SimpleNamespace(id="OBJ_1", object_ref=obj)
        root_obj = root(scps=[SimpleNamespace(id="S1", bound_objects=[entry])])
        root_obj.af_shortcut_system.shortcuts = FakeShortcutCollection()
        scn = scene(root_obj, obj)
        scn.af_new_shortcut_name = "Arm X"
        scn.af_new_shortcut_path = 'bpy.data.objects["bound"].location[0]'
        ctx = context(scn)
        self.assertEqual(add_shortcut_from_context(ctx), (True, ""))
        row = root_obj.af_shortcut_system.shortcuts[0]
        self.assertEqual((row.name, row.owner_type, row.owner_id), ("Arm X", "SCP", "S1"))
        self.assertEqual((scn.af_new_shortcut_name, scn.af_new_shortcut_path), ("", ""))
        self.assertTrue(delete_shortcut_from_context(ctx, row.id))
        self.assertEqual(len(root_obj.af_shortcut_system.shortcuts), 0)

    def test_shortcut_use_case_reports_validation_errors(self):
        root_obj = root(scps=[scp("S1")])
        root_obj.af_shortcut_system.shortcuts = FakeShortcutCollection()
        scn = scene(root_obj)
        scn.af_new_shortcut_name = ""
        scn.af_new_shortcut_path = ""
        self.assertEqual(add_shortcut_from_context(context(scn)), (False, "Enter a shortcut name."))
        scn.af_new_shortcut_name = "Arm X"
        self.assertEqual(add_shortcut_from_context(context(scn)), (False, "Paste a full Blender data path that points to an object bound to the active SCP."))


if __name__ == "__main__":
    unittest.main()
