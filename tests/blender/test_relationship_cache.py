"""Real RNA, history, ownership and persistence regressions for AF-14."""
import os
from pathlib import Path
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, root, fiber, mesh_object, scp_with_object
from anthroforge.core.deps import runtime_context_build as build, relationship_cache as cache
from anthroforge.core.vcp import fiber_node_attachment_codec as codec
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.utils import get_af_root


def fixture():
    owner = root()
    with suppress_vcp_prop_updates():
        first = scp_with_object(owner, "First", mesh_object("First"))
        second = scp_with_object(owner, "Second", mesh_object("Second"))
        item = fiber(owner, first.id, second.id)
        item.node_attachments_json = payload(first.id)
    return owner, item, first.id, second.id


def payload(target):
    node = codec.FiberNodeAttachment(target, "attachment", (0., 0., 0.))
    return codec.encode_node_attachments(codec.FiberNodeAttachmentPayload(2, 2, False, (node, node)))


def graph(owner):
    return build._cached_graph_data(owner, bpy.context.scene)


def parity(owner):
    cached, uncached = graph(owner), build._graph_data(owner)
    assert cached[0].ports or not owner.af_scp_system.scps
    assert cached[0].ports == uncached[0].ports
    assert cached[0].edges == uncached[0].edges
    assert cached[1:] == uncached[1:]
    for entity in cached[0].entity_adjacency():
        assert cached[0].downstream_entities({entity}) == uncached[0].downstream_entities({entity})


class RelationshipCacheBlenderTests(BlenderTestCase):
    def test_raw_payload_and_suppressed_binding_writes(self):
        owner, item, first, second = fixture(); before = graph(owner)
        with patch.object(codec, "decode_node_attachments", wraps=codec.decode_node_attachments) as decode:
            self.assertIs(before, graph(owner)); self.assertEqual(decode.call_count, 0)
            item["node_attachments_json"] = payload(second)
            self.assertIsNot(before, graph(owner)); self.assertEqual(decode.call_count, 1)
        before = graph(owner)
        with suppress_vcp_prop_updates(): item.a_parent_id = second
        self.assertIsNot(before, graph(owner)); parity(owner)

    def test_same_count_shared_point_replacement(self):
        owner, item, first, second = fixture(); before = graph(owner)
        points = owner.af_vcp_system.authored_points; key = item.a_point_id
        index = next(i for i, point in enumerate(points) if point.id == key)
        with suppress_vcp_prop_updates():
            points.remove(index); replacement = points.add(); replacement.id = key; replacement.parent_id = second
        self.assertIsNot(before, graph(owner)); self.assertEqual(item.a_parent_id, second); parity(owner)

    def test_touch_loop_raw_rebinding_and_entity_membership(self):
        owner, item, first, second = fixture()
        with suppress_vcp_prop_updates():
            touch = item.mid_touches.add(); touch.parent_id = first
        before = graph(owner)
        with suppress_vcp_prop_updates(): touch.parent_id = second
        self.assertIsNot(before, graph(owner)); parity(owner); before = graph(owner)
        with suppress_vcp_prop_updates():
            item.topology_mode = "LOOP"; anchor = item.loop_anchors.add(); anchor.parent_id = first
        self.assertIsNot(before, graph(owner)); parity(owner)

    def test_afi_remap_duplicate_and_same_name_object_recreation(self):
        owner, item, first, second = fixture()
        obj = bpy.data.objects["First"]; obj["af_authoring_id"] = "test"
        obj["af_source_scp_id"] = first; item["node_attachments_json"] = payload("AFI_test")
        before = graph(owner); obj["af_source_scp_id"] = second
        self.assertIsNot(before, graph(owner)); parity(owner); before = graph(owner)
        duplicate = obj.copy(); bpy.context.scene.collection.objects.link(duplicate)
        self.assertIsNot(before, graph(owner)); parity(owner)
        bpy.data.objects.remove(duplicate, do_unlink=True)
        self.assertIsNot(before, graph(owner)); parity(owner)

    def test_same_count_fiber_and_same_name_instance_recreation(self):
        owner, item, first, second = fixture(); before = graph(owner)
        with suppress_vcp_prop_updates():
            identity = item.id; owner.af_vcp_system.fibers.remove(0)
            item = fiber(owner, first, second); item.id = identity
        self.assertIsNot(before, graph(owner)); parity(owner)
        obj = bpy.data.objects["First"]; obj["af_authoring_id"] = "replacement"
        item["node_attachments_json"] = payload("AFI_replacement"); before = graph(owner)
        replacement = obj.copy(); bpy.context.scene.collection.objects.link(replacement)
        name = obj.name; bpy.data.objects.remove(obj, do_unlink=True); replacement.name = name
        self.assertIsNot(before, graph(owner)); parity(owner)

    def test_undo_redo_invalidates_epoch_and_restores_graph(self):
        owner, item, first, second = fixture(); name = owner.name
        bpy.ops.ed.undo_push(message="AF14 before"); before = graph(owner); epoch = cache._EPOCH
        item["node_attachments_json"] = payload(second); bpy.ops.ed.undo_push(message="AF14 after")
        graph(owner); bpy.ops.ed.undo(); owner = bpy.data.objects[name]
        self.assertGreater(cache._EPOCH, epoch); self.assertIsNot(before, graph(owner)); parity(owner)
        self.assertEqual(codec.node_attachment_target_ids(owner.af_vcp_system.fibers[0]), (first,))
        bpy.ops.ed.redo(); owner = bpy.data.objects[name]; parity(owner)
        self.assertEqual(codec.node_attachment_target_ids(owner.af_vcp_system.fibers[0]), (second,))

    def test_save_load_recreation_and_cache_scope(self):
        owner, item, first, second = fixture(); previous = graph(owner); name = owner.name
        folder = Path(os.environ["AF14_ARTIFACT_DIR"]); folder.mkdir(parents=True, exist_ok=True)
        path = folder / "cache_lifecycle.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
        bpy.ops.wm.open_mainfile(filepath=str(path)); owner = bpy.data.objects[name]
        self.assertIsNot(previous, graph(owner)); parity(owner); previous = graph(owner)
        bpy.data.objects.remove(owner, do_unlink=True); owner = root()
        self.assertIsNot(previous, graph(owner)); parity(owner)

    def test_duplicate_roots_and_different_scene_namespace(self):
        owner, item, first, second = fixture(); previous = graph(owner)
        duplicate = owner.copy(); bpy.context.scene.collection.objects.link(duplicate)
        self.assertIsNot(previous, graph(duplicate)); parity(duplicate)
        other = bpy.data.scenes.new("Other"); other.collection.objects.link(owner)
        self.assertIsNot(previous, build._cached_graph_data(owner, other))
        self.assertIs(graph(owner), graph(owner))

    def test_unregister_clears_owner_and_graph_budgets(self):
        from anthroforge.core.visualization.fiber_cache_lifecycle import unregister_fiber_cache_lifecycle, register_fiber_cache_lifecycle
        from anthroforge.core.utils import bounded_scene_cache_stats
        owner, *_ = fixture(); graph(owner)
        self.assertGreater(bounded_scene_cache_stats(cache.GRAPH_NAMESPACE)["entries"], 0)
        unregister_fiber_cache_lifecycle()
        self.assertEqual(bounded_scene_cache_stats(cache.GRAPH_NAMESPACE)["entries"], 0)
        self.assertEqual(bounded_scene_cache_stats(cache.OWNER_NAMESPACE)["entries"], 0)
        register_fiber_cache_lifecycle()
