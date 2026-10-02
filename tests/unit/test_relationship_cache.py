"""Relationship cache correctness independent of Blender evaluation/numerics."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support import install_fake_modules
install_fake_modules()
from core.deps import adapters, drivers, relationship_cache as cache, runtime_context_build as build
from core import utils
from core.vcp import fiber_node_attachment_codec as codec


def payload(target="S1", offset=0):
    node = codec.FiberNodeAttachment(target, "A", (offset, 0., 0.))
    return codec.encode_node_attachments(codec.FiberNodeAttachmentPayload(2, 2, False, (node, node)))


def fiber(identity="F1", raw=None):
    return NS(id=identity, topology_mode="OPEN", a_parent_id="S1", b_parent_id="S2",
              a_point_id="", b_point_id="", mid_touches=[], loop_anchors=[],
              node_attachments_json=payload() if raw is None else raw)


def root():
    vcp = NS(fibers=[fiber()], fiber_surfaces=[], muscles=[], blobs=[], soft_tissues=[], authored_points=[])
    return NS(af_vcp_system=vcp, af_scp_system=NS(scps=[NS(id="S1", parent_id=""), NS(id="S2", parent_id="")]),
              users_scene=(), name="root")


class Driver:
    name = "relationships"

    def entity_types(self):
        return "SCP", "FIBER", "FIBER_SURFACE", "MUSCLE", "BLOB", "SOFT_TISSUE"

    def build_graph(self, owner, graph, entity_sets):
        entity_sets.update(adapters.build_runtime_graph(owner, graph))


def canonical(data):
    graph, entities, adjacency, indices, sizes = data
    components = {frozenset(key for key, value in indices.items() if value == index) for index in sizes}
    return graph.ports, graph.edges, entities, dict(adjacency), components


class RelationshipCacheTests(unittest.TestCase):
    def setUp(self):
        self.registry = patch.dict(drivers._DRIVERS, {}, clear=True); self.registry.start()
        drivers.register_dependency_driver(Driver())
        cache.clear_relationship_cache(); self.root = root(); self.scene = NS(session_uid=101)

    def tearDown(self):
        self.registry.stop(); cache.clear_relationship_cache()

    def get(self):
        return build._cached_graph_data(self.root, self.scene)

    def assert_parity(self):
        self.assertEqual(canonical(self.get()), canonical(build._graph_data(self.root)))

    def test_warm_no_decode_or_rebuild_and_coordinates_keep_graph(self):
        first = self.get()
        with patch.object(codec, "decode_node_attachments", wraps=codec.decode_node_attachments) as decode:
            self.assertIs(first, self.get()); self.assertEqual(decode.call_count, 0)
            self.root.af_vcp_system.fibers[0].node_attachments_json = payload(offset=5)
            self.assertIs(first, self.get()); self.assertEqual(decode.call_count, 1)
        self.assert_parity()

    def test_valid_invalid_valid_and_exact_raw_comparison(self):
        item = self.root.af_vcp_system.fibers[0]; first = self.get()
        item.node_attachments_json = '{"version":2,"nodes":[]}'
        self.assertIsNot(first, self.get()); self.assert_parity()
        item.node_attachments_json = payload("S2"); second = self.get()
        self.assertEqual(cache.node_owner_ids(self.root, self.scene, item), ("S2",))
        item.node_attachments_json = payload("S1")
        self.assertIsNot(second, self.get()); self.assert_parity()

    def test_influence_owners_preserve_validated_order(self):
        value = json.loads(payload())
        value["nodes"][0]["influences"] = [dict(value["nodes"][0], weight=.4),
            dict(value["nodes"][0], target_id="S3", weight=.6)]
        item = self.root.af_vcp_system.fibers[0]; item.node_attachments_json = json.dumps(value)
        self.assertEqual(cache.node_owner_ids(self.root, self.scene, item), ("S1", "S3"))
        self.assert_parity()

    def test_all_fiber_relationship_changes_rebuild(self):
        item = self.root.af_vcp_system.fibers[0]
        changes = (("a_parent_id", "S3"), ("a_point_id", "P1"), ("b_parent_id", "S4"),
                   ("mid_touches", [NS(point_id="P2", parent_id="S5")]), ("topology_mode", "LOOP"),
                   ("loop_anchors", [NS(point_id="P3", parent_id="S6", attach_param="0.5")]))
        for name, value in changes:
            previous = self.get(); setattr(item, name, value)
            self.assertIsNot(previous, self.get()); self.assert_parity()

    def test_surface_membership_and_branches(self):
        surface = NS(id="FS", fiber_refs=[], construction_mode="BRANCHED_LOFT", main_surface_id="A", branches=[])
        self.root.af_vcp_system.fiber_surfaces.append(surface)
        for name, value in (("main_surface_id", "B"), ("branches", [NS(surface_id="C")]),
                            ("fiber_refs", [NS(fiber_id="F1")]), ("construction_mode", "LOFT")):
            previous = self.get(); setattr(surface, name, value)
            self.assertIsNot(previous, self.get()); self.assert_parity()

    def test_same_count_replacement_and_duplicate_ids(self):
        first = self.get(); self.root.af_vcp_system.fibers[0] = fiber()
        self.assertIsNot(first, self.get())
        self.root.af_vcp_system.fibers.append(fiber())
        self.assertIsNot(self.get(), self.get()); self.assert_parity()

    def test_roots_scenes_and_targeted_clear(self):
        first = self.get(); original = self.root; self.root = root(); second = self.get()
        self.assertIsNot(first, second); cache.clear_relationship_cache(original)
        self.assertIs(second, self.get()); self.root = original
        self.assertIsNot(first, self.get()); first = self.get(); self.scene = NS(session_uid=102)
        self.assertIsNot(first, self.get())

    def test_epoch_clear_recreation_and_driver_replacement(self):
        first = self.get(); before = cache.capture_relationships(self.root, self.scene).key
        cache.clear_relationship_cache()
        self.assertNotEqual(before, cache.capture_relationships(self.root, self.scene).key)
        self.assertIsNot(first, self.get()); first = self.get()
        drivers.register_dependency_driver(Driver(), replace=True)
        self.assertIsNot(first, self.get()); first = self.get(); self.root = root()
        self.assertIsNot(first, self.get())

    def test_owner_eviction_and_oversize(self):
        with patch.object(cache, "OWNER_ENTRIES", 1):
            cache.node_owner_ids(self.root, self.scene, self.root.af_vcp_system.fibers[0])
            cache.node_owner_ids(self.root, self.scene, fiber("F2"))
            self.assertEqual(utils.bounded_scene_cache_stats(cache.OWNER_NAMESPACE)["entries"], 1)
        cache.clear_relationship_cache()
        with patch.object(cache, "OWNER_BYTES", 1):
            self.get(); self.assertEqual(utils.bounded_scene_cache_stats(cache.OWNER_NAMESPACE)["entries"], 0)

    def test_graph_eviction_fresh_generation_and_oversize(self):
        with patch.object(cache, "GRAPH_ENTRIES", 1):
            first = self.get(); cap = cache.capture_relationships(self.root, self.scene)
            generation = cache.graph_entry(cap)[1]; original = self.root; self.root = root(); self.get()
            self.root = original; self.assertIsNot(first, self.get())
            self.assertGreater(cache.graph_entry(cap)[1], generation)
        cache.clear_relationship_cache()
        with patch.object(cache, "GRAPH_BYTES", 1):
            self.assertIsNot(self.get(), self.get())
            self.assertEqual(utils.bounded_scene_cache_stats(cache.GRAPH_NAMESPACE)["bytes"], 0)

    def test_graph_accounting_traverses_ports_edges_and_sets(self):
        data = self.get(); cap = cache.capture_relationships(self.root, self.scene)
        entry = cache.graph_entry(cap); size = utils.bounded_scene_cache_stats(cache.GRAPH_NAMESPACE)["bytes"]
        self.assertGreater(size, utils._bounded_size((cap.key, entry)))
        self.assertLessEqual(size, cache.GRAPH_BYTES)

    def test_other_entity_relationship_fields(self):
        vcp = self.root.af_vcp_system
        muscle = NS(id="M", surface_source_mode="LEGACY_FIBERS", fiber_surface_id="", fiber_refs=[], use_mirrored_rows=False)
        blob = NS(id="B", attach_target_type="SCP", attach_target_id="S1")
        vcp.muscles.append(muscle); vcp.blobs.append(blob)
        changes = ((muscle, "surface_source_mode", "FIBER_SURFACE"), (muscle, "fiber_surface_id", "FS"),
                   (muscle, "fiber_refs", [NS(fiber_id="F1")]), (muscle, "use_mirrored_rows", True),
                   (blob, "attach_target_type", "MUSCLE"), (blob, "attach_target_id", "M"),
                   (self.root.af_scp_system.scps[1], "parent_id", "S1"))
        for item, field, value in changes:
            before = self.get(); setattr(item, field, value)
            self.assertIsNot(before, self.get()); self.assert_parity()

    def test_failed_driver_registration_keeps_generation(self):
        generation = drivers.dependency_driver_generation(); previous = self.get()
        with self.assertRaises(ValueError): drivers.register_dependency_driver(Driver())
        self.assertEqual(drivers.dependency_driver_generation(), generation)
        self.assertIs(previous, self.get())

    def test_missing_ambiguous_resolved_afi_are_distinct(self):
        from core.scp_runtime import common
        self.root.users_scene = (self.scene,)
        self.root.af_vcp_system.fibers[0].node_attachments_json = payload("AFI_abc")
        with patch.object(common, "instance_geometry_index", return_value=({}, frozenset())) as resolve:
            missing = self.get(); resolve.return_value = ({}, frozenset({"AFI_abc"}))
            ambiguous = self.get(); self.assertIsNot(missing, ambiguous)
            resolve.return_value = ({"AFI_abc": {"af_source_scp_id": "S2"}}, frozenset())
            self.assertIsNot(ambiguous, self.get()); self.assert_parity()

    def test_afi_mapping_once_per_capture_and_uncached_parity(self):
        from core.scp_runtime import common
        self.root.users_scene = (self.scene,)
        self.root.af_vcp_system.fibers[0].node_attachments_json = payload("AFI_abc")
        obj = {"af_source_scp_id": "S1"}
        with patch.object(common, "instance_geometry_index", return_value=({"AFI_abc": obj}, frozenset())) as resolve:
            first = self.get(); self.assertEqual(resolve.call_count, 1)
            self.assertIs(first, self.get()); self.assertEqual(resolve.call_count, 2)
            obj["af_source_scp_id"] = "S2"
            self.assertIsNot(first, self.get()); self.assertEqual(resolve.call_count, 3)
            self.assert_parity()


if __name__ == "__main__":
    unittest.main()
