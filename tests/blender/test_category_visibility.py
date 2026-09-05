from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import bpy
import anthroforge
from mathutils import Vector

from _helpers import BlenderTestCase, empty_object, mesh_object, root
from anthroforge.app.queries.tree import tree_panel_state
from anthroforge.core.visualization import category_visibility as visibility
from anthroforge.core.visualization import fiber_anchor_overlay as overlay
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.ui.panels.tree_panel import AF_PT_TreePanel


def _entities():
    owner = root()
    with suppress_vcp_prop_updates():
        muscle = owner.af_vcp_system.muscles.add()
        muscle.id, muscle.name = "M1", "Muscle"
        for fid, mid in (("F1", "M1"), ("F2", "")):
            fiber = owner.af_vcp_system.fibers.add()
            fiber.id, fiber.name, fiber.muscle_id = fid, fid, mid
    return owner


def _object(owner, name, category, entity_id, role="proxy", mirror=False):
    obj = mesh_object(name) if role == "proxy" else empty_object(name)
    kind = category.lower()
    obj["af_root_name"], obj[f"af_{kind}_id"] = owner.name, entity_id
    obj[f"af_{kind}_{role}"] = True
    if mirror:
        obj[f"af_{kind}_mirror_proxy"] = True
        obj[f"af_source_{kind}_id"] = entity_id
    return obj


def _objects(owner, category, entity_id):
    _, roles = visibility.CATEGORY_ROLES[category]
    objects = [_object(owner, role, category, entity_id, role.removeprefix(f"af_{category.lower()}_"))
               for role in roles]
    objects.append(_object(owner, category + " mirror", category, entity_id, mirror=True))
    if category == "MUSCLE":
        objects.append(_object(owner, "Inflated", category, entity_id))
        objects[-1]["af_muscle_surface"] = "INFL"
    return objects


def _hide(category, hidden=True):
    return bpy.ops.af.set_vcp_category_visibility(category=category, hidden=hidden)


def _hidden(objects, layer=None):
    return tuple(obj.hide_get(view_layer=layer or bpy.context.view_layer) for obj in objects)


def _snapshot(owner, objects):
    geometry = tuple((obj.name, tuple(tuple(row) for row in obj.matrix_world),
                      tuple(tuple(v.co) for v in obj.data.vertices) if obj.type == "MESH" else (),
                      obj.hide_viewport, obj.hide_render) for obj in objects)
    system = owner.af_vcp_system
    entities = tuple((fiber.id, fiber.muscle_id, fiber.a_attach_param, fiber.b_attach_param)
                     for fiber in system.fibers)
    scene = bpy.context.scene
    return geometry, entities, len(scene.objects), len(system.muscles), scene.af_vcp_tree_collapsed_json


def _restricted_collection(obj):
    collection = bpy.data.collections.new("Restricted")
    bpy.context.scene.collection.children.link(collection)
    for previous in tuple(obj.users_collection):
        previous.objects.unlink(obj)
    collection.objects.link(obj)
    bpy.context.view_layer.update()
    return bpy.context.view_layer.layer_collection.children[collection.name]


class RecordingLayout:
    def __init__(self, records=None):
        self.records, self.enabled = records if records is not None else [], True

    def row(self, **kwargs):
        return RecordingLayout(self.records)

    def box(self):
        return self.row()

    def label(self, **kwargs):
        self.records.append(("label", kwargs.get("text", "")))

    def separator(self):
        pass

    def operator(self, name, **kwargs):
        operator = NS(name=name, enabled=self.enabled, text=kwargs.get("text", ""))
        self.records.append(("operator", operator))
        return operator


def _category_actions():
    layout = RecordingLayout()
    AF_PT_TreePanel.draw(NS(layout=layout), bpy.context)
    return [value for kind, value in layout.records if kind == "operator"
            and value.name == "af.set_vcp_category_visibility"]


class CategoryVisibilityBlenderTests(BlenderTestCase):
    def test_tested_addon_and_modules_are_this_worktree(self):
        addon = Path(__file__).resolve().parents[2]
        self.assertEqual(Path(anthroforge.__file__).resolve(), addon / "__init__.py")
        for module in (visibility, overlay):
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(addon))

    def test_categories_all_roles_mirrors_and_two_layers_are_independent(self):
        owner = _entities()
        muscles, fibers = _objects(owner, "MUSCLE", "M1"), _objects(owner, "FIBER", "F1")
        second = bpy.context.scene.view_layers.new("Second")
        bpy.context.view_layer.update()
        self.assertEqual(_hide("MUSCLE"), {"FINISHED"})
        self.assertTrue(all(_hidden(muscles)))
        self.assertFalse(any(_hidden(fibers) + _hidden(muscles, second)))
        self.assertEqual(_hide("FIBER"), {"FINISHED"})
        self.assertTrue(all(_hidden(fibers)))
        _hide("MUSCLE", False)
        self.assertFalse(any(_hidden(muscles)))
        self.assertTrue(all(_hidden(fibers)))
        self.assertFalse(any(_hidden(fibers, second)))

    def test_other_root_other_categories_stale_and_unrelated_are_untouched(self):
        owner, other = _entities(), empty_object("OTHER_ROOT")
        selected = _object(other, "OtherFiber", "FIBER", "F1")
        unrelated = [_object(owner, "Stale", "FIBER", "OLD"), selected, mesh_object("Unrelated")]
        unrelated += [_object(owner, category, category, "F1") for category in
                      ("FIBER_SURFACE", "BLOB", "SOFT_TISSUE", "SCP")]
        target = _object(owner, "Target", "FIBER", "F1")
        bpy.context.view_layer.objects.active = selected
        selected.select_set(True)
        _hide("FIBER")
        self.assertTrue(target.hide_get())
        self.assertFalse(any(_hidden(unrelated)))
        self.assertEqual(bpy.context.view_layer.objects.active, selected)
        self.assertTrue(selected.select_get())

    def test_collapsed_and_free_fibers_change_without_geometry_or_data_changes(self):
        owner = _entities()
        fibers = [_object(owner, fid, "FIBER", fid) for fid in ("F1", "F2")]
        bpy.context.scene.af_vcp_tree_collapsed_json = '{"MUSCLE:M1": true}'
        before = _snapshot(owner, fibers)
        _hide("FIBER")
        self.assertTrue(all(_hidden(fibers)))
        self.assertEqual(_snapshot(owner, fibers), before)
        _hide("FIBER", False)
        self.assertFalse(any(_hidden(fibers)))
        self.assertEqual(_snapshot(owner, fibers), before)

    def test_live_status_and_repeat_action_follow_outliner_edits(self):
        owner = _entities()
        objects = [_object(owner, fid, "FIBER", fid) for fid in ("F1", "F2")]
        objects[0].hide_set(True)
        self.assertEqual(tree_panel_state(bpy.context).fiber_visibility.status, "Mixed")
        _hide("FIBER")
        self.assertEqual(tree_panel_state(bpy.context).fiber_visibility.status, "All hidden")
        result = visibility.set_category_visibility(bpy.context.scene, bpy.context.view_layer, owner, "FIBER", True)
        self.assertEqual(result.changed, 0)
        objects[0].hide_set(False)
        self.assertEqual(tree_panel_state(bpy.context).fiber_visibility.status, "Mixed")

    def test_excluded_collection_is_unavailable_without_touching_other_layer(self):
        owner = _entities()
        obj = _object(owner, "ExcludedFiber", "FIBER", "F1")
        collection = _restricted_collection(obj)
        second = bpy.context.scene.view_layers.new("Second")
        collection.exclude = True
        bpy.context.view_layer.update()
        state = tree_panel_state(bpy.context).fiber_visibility
        self.assertEqual((state.status, state.unavailable, state.available), ("Unavailable", 1, 0))
        self.assertEqual(_hide("FIBER"), {"FINISHED"})
        self.assertTrue(collection.exclude)
        self.assertFalse(obj.hide_get(view_layer=second))

    def test_show_preserves_global_render_and_collection_restrictions(self):
        owner = _entities()
        obj = _object(owner, "RestrictedFiber", "FIBER", "F1")
        layer_collection = _restricted_collection(obj)
        obj.hide_viewport, obj.hide_render, layer_collection.hide_viewport = True, True, True
        obj.hide_set(True)
        _hide("FIBER", False)
        self.assertFalse(obj.hide_get())
        self.assertTrue(obj.hide_viewport and obj.hide_render and layer_collection.hide_viewport)
        self.assertFalse(obj.visible_get())
        self.assertEqual(tree_panel_state(bpy.context).fiber_visibility.status, "All unhidden")

    def test_controls_remain_present_for_empty_and_collapsed_tree(self):
        root()
        empty_actions = _category_actions()
        self.assertEqual([(op.category, op.hidden) for op in empty_actions],
                         [("MUSCLE", False), ("MUSCLE", True), ("FIBER", False), ("FIBER", True)])
        self.assertFalse(any(op.enabled for op in empty_actions))
        owner = _entities()
        _object(owner, "Fiber", "FIBER", "F1")
        bpy.context.scene.af_vcp_tree_collapsed_json = '{"MUSCLE:M1": true}'
        actions = _category_actions()
        self.assertEqual([op.text for op in actions], ["Show", "Hide", "Show", "Hide"])
        self.assertEqual([op.enabled for op in actions], [False, False, True, True])

    def test_existing_fiber_proxy_hide_survives_ordinary_sync(self):
        owner = _entities()
        fiber = owner.af_vcp_system.fibers[0]
        sync = register_fiber_sync()
        points = [Vector((float(index), 0.0, 0.0)) for index in range(fiber.node_count)]
        proxy = sync.apply_points(owner, bpy.context.scene, fiber, points)
        _hide("FIBER")
        sync.sync_root_to_scene(owner, bpy.context.scene, target_fiber_ids={fiber.id})
        self.assertTrue(proxy.hide_get())

    def test_overlay_hide_show_preserves_cached_batch(self):
        owner = _entities()
        _object(owner, "Source", "FIBER", "F1")
        bpy.context.view_layer.update()
        owner.af_vcp_system.active_vcp_type, owner.af_vcp_system.active_vcp_id = "FIBER", "F1"
        with patch.object(overlay, "_CONTEXT_PROVIDER", lambda: bpy.context), \
             patch("anthroforge.core.vcp.fiber_anchor_preflight.fiber_anchor_scope", return_value="scope"), \
             patch.dict(overlay._BATCHES, {"scope": ("key", "batch")}, clear=True):
            self.assertEqual(overlay._active_batch(), "batch")
            _hide("FIBER")
            self.assertIsNone(overlay._active_batch())
            self.assertEqual(overlay._BATCHES["scope"], ("key", "batch"))
            _hide("FIBER", False)
            self.assertEqual(overlay._active_batch(), "batch")
