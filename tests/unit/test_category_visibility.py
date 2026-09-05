from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

for path in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from _support import install_fake_modules
install_fake_modules()
from core.visualization import category_visibility as visibility
from core.visualization import fiber_anchor_overlay as overlay
from app.use_cases import category_visibility as use_case
from app.queries import tree
from ui.sections.category_visibility import draw_category_visibility


class Object(dict):
    def __init__(self, name, category="FIBER", owner="F1", role="proxy", root="ROOT"):
        super().__init__(af_root_name=root)
        self.name, self.states, self.writes, self.blocked = name, {}, [], False
        self[f"af_{category.lower()}_id"] = owner
        self[f"af_{category.lower()}_{role}"] = True

    def hide_get(self, *, view_layer):
        return self.states.get(id(view_layer), False)

    def hide_set(self, hidden, *, view_layer):
        self.states[id(view_layer)] = hidden
        self.writes.append((hidden, view_layer))

    def visible_get(self, *, view_layer, viewport=None):
        return not self.blocked and not self.hide_get(view_layer=view_layer)


def fixture(*objects):
    system = NS(fibers=[NS(id="F1"), NS(id="F2")], muscles=[NS(id="M1")])
    root = NS(name="ROOT", af_vcp_system=system)
    scene, layer = NS(objects=list(objects)), NS(objects={obj.name: obj for obj in objects})
    return scene, layer, root


def mirrored(name, category="FIBER", source="F1"):
    obj = Object(name, category, "OLD")
    obj[f"af_{category.lower()}_mirror_proxy"] = True
    obj[f"af_source_{category.lower()}_id"] = source
    return obj


class CategoryVisibilityTests(unittest.TestCase):
    def test_every_role_and_mirror_is_owned(self):
        for category, (_, roles) in visibility.CATEGORY_ROLES.items():
            owner = "M1" if category == "MUSCLE" else "F1"
            objects = [Object(role, category, owner, role.removeprefix(f"af_{category.lower()}_"))
                       for role in roles] + [mirrored("mirror", category, owner)]
            scene, layer, root = fixture(*objects)
            self.assertEqual(visibility.category_objects(scene, root, category), tuple(objects))
            result = visibility.set_category_visibility(scene, layer, root, category, True)
            self.assertEqual((result.changed, result.hidden), (len(objects), len(objects)))

    def test_other_roots_categories_and_stale_ids_are_excluded(self):
        objects = [Object("other", root="OTHER"), Object("stale", owner="DELETED"),
                   Object("surface", "FIBER_SURFACE"), Object("muscle", "MUSCLE", "M1"),
                   Object("untagged", role="unused"), mirrored("stale-source", source="DELETED")]
        scene, layer, root = fixture(*objects)
        self.assertEqual(visibility.set_category_visibility(scene, layer, root, "FIBER", True).changed, 0)
        self.assertFalse(any(obj.writes for obj in objects))

    def test_mirror_without_source_uses_ordinary_live_id(self):
        obj = Object("mirror")
        obj["af_fiber_mirror_proxy"] = True
        scene, _, root = fixture(obj)
        self.assertEqual(visibility.category_objects(scene, root, "FIBER"), (obj,))

    def test_live_mixed_status_changes_after_external_edit(self):
        first, second = Object("one"), Object("two", owner="F2")
        scene, layer, root = fixture(first, second)
        second.hide_set(True, view_layer=layer)
        self.assertEqual(visibility.category_visibility(scene, layer, root, "FIBER").status, "Mixed")
        first.hide_set(True, view_layer=layer)
        self.assertEqual(visibility.category_visibility(scene, layer, root, "FIBER").status, "All hidden")
        visibility.set_category_visibility(scene, layer, root, "FIBER", False)
        self.assertEqual(visibility.category_visibility(scene, layer, root, "FIBER").status, "All unhidden")

    def test_empty_missing_root_and_bad_category_are_safe(self):
        scene, layer, root = fixture()
        for selected_root, category in ((root, "FIBER"), (None, "FIBER"), (root, "WRONG")):
            result = visibility.set_category_visibility(scene, layer, selected_root, category, True)
            self.assertEqual((result.status, result.changed), ("No objects", 0))

    def test_absent_and_unreadable_objects_are_unavailable(self):
        absent, broken = Object("absent"), Object("broken")
        scene, layer, root = fixture(absent, broken)
        del layer.objects[absent.name]
        broken.hide_get = Mock(side_effect=ReferenceError("deleted"))
        result = visibility.set_category_visibility(scene, layer, root, "FIBER", True)
        self.assertEqual((result.status, result.unavailable, result.available), ("Unavailable", 2, 0))
        self.assertEqual((absent.writes, broken.writes), ([], []))

    def test_failed_write_reports_unavailable_and_not_changed(self):
        obj = Object("broken")
        scene, layer, root = fixture(obj)
        obj.hide_set = Mock(side_effect=RuntimeError("unavailable"))
        result = visibility.set_category_visibility(scene, layer, root, "FIBER", True)
        self.assertEqual((result.changed, result.unavailable), (0, 1))

    def test_category_and_view_layer_independence_and_idempotency(self):
        fib, muscle = Object("fiber"), Object("muscle", "MUSCLE", "M1")
        scene, layer, root = fixture(fib, muscle)
        other_layer = NS(objects=layer.objects)
        visibility.set_category_visibility(scene, layer, root, "MUSCLE", True)
        result = visibility.set_category_visibility(scene, layer, root, "MUSCLE", True)
        self.assertEqual(result.changed, 0)
        self.assertEqual(len(muscle.writes), 1)
        self.assertFalse(muscle.hide_get(view_layer=other_layer))
        self.assertFalse(fib.hide_get(view_layer=layer))

    def test_new_objects_are_live_not_a_persistent_filter(self):
        obj = Object("one")
        scene, layer, root = fixture(obj)
        visibility.set_category_visibility(scene, layer, root, "FIBER", True)
        late = Object("late")
        scene.objects.append(late)
        layer.objects[late.name] = late
        self.assertEqual(visibility.category_visibility(scene, layer, root, "FIBER").status, "Mixed")

    def test_use_case_uses_same_root_as_tree_query_and_redraws_only_viewports(self):
        obj = Object("fiber")
        scene, layer, root = fixture(obj)
        view, other = NS(type="VIEW_3D", tag_redraw=Mock()), NS(type="OUTLINER", tag_redraw=Mock())
        manager = NS(windows=[NS(screen=NS(areas=[view, other]))])
        context = NS(scene=scene, view_layer=layer, window_manager=manager)
        self.assertIs(use_case.root_for_context, tree.root_for_context)
        with patch.object(use_case, "root_for_context", return_value=root):
            self.assertTrue(use_case.set_vcp_category_visibility(context, "FIBER", True).ok)
        view.tag_redraw.assert_called_once()
        other.tag_redraw.assert_not_called()


class Layout:
    def __init__(self, records=None):
        self.records, self.enabled = records if records is not None else [], True

    def row(self, **kwargs):
        return Layout(self.records)

    def label(self, **kwargs):
        self.records.append(("label", kwargs["text"]))

    def operator(self, name, **kwargs):
        op = NS(name=name, enabled=self.enabled, label=kwargs["text"])
        self.records.append(("operator", op))
        return op


class CategoryVisibilityDrawingTests(unittest.TestCase):
    def test_explicit_actions_and_honest_empty_and_unavailable_status(self):
        layout = Layout()
        draw_category_visibility(layout, visibility.CategoryVisibility(), visibility.CategoryVisibility(1, 1, 2))
        actions = [value for kind, value in layout.records if kind == "operator"]
        self.assertEqual([(op.category, op.hidden, op.label) for op in actions],
                         [("MUSCLE", False, "Show"), ("MUSCLE", True, "Hide"),
                          ("FIBER", False, "Show"), ("FIBER", True, "Hide")])
        self.assertEqual([op.enabled for op in actions], [False, False, True, True])
        self.assertIn(("label", "No objects"), layout.records)
        self.assertIn(("label", "Mixed (2 unavailable)"), layout.records)

    def test_hidden_fiber_suppresses_overlay_without_losing_cache(self):
        obj = Object("source")
        scene, layer, root = fixture(obj)
        root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "FIBER", "F1"
        context = NS(scene=scene, view_layer=layer)
        with patch.object(overlay, "_CONTEXT_PROVIDER", lambda: context), \
             patch.object(overlay, "_root_for_scene", return_value=root), \
             patch("core.vcp.fiber_anchor_preflight.fiber_anchor_scope", return_value="scope"), \
             patch.dict(overlay._BATCHES, {"scope": ("key", "batch")}, clear=True):
            self.assertEqual(overlay._active_batch(), "batch")
            visibility.set_category_visibility(scene, layer, root, "FIBER", True)
            self.assertIsNone(overlay._active_batch())
            self.assertEqual(overlay._BATCHES["scope"], ("key", "batch"))
            visibility.set_category_visibility(scene, layer, root, "FIBER", False)
            self.assertEqual(overlay._active_batch(), "batch")

    def test_effective_visibility_requires_source_not_mirror_or_controls(self):
        source, mirror, handle = Object("source"), mirrored("mirror"), Object("handle", role="touch_handle")
        scene, layer, root = fixture(source, mirror, handle)
        source.blocked = True
        self.assertFalse(visibility.fiber_proxy_visible(scene, layer, root, "F1"))
        source.blocked = False
        self.assertTrue(visibility.fiber_proxy_visible(scene, layer, root, "F1"))
        del layer.objects[source.name]
        self.assertFalse(visibility.fiber_proxy_visible(scene, layer, root, "F1"))


if __name__ == "__main__":
    unittest.main()
