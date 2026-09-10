from pathlib import Path
import importlib.util
import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path
from core.vcp.fiber_node_attachment_codec import (FiberNodeAttachment,
                                                   FiberNodeAttachmentPayload,
                                                   encode_node_attachments)

ensure_import_path()

PKG = types.ModuleType("deps_test")
PKG.__path__ = [str(ADDON_ROOT / "core" / "deps")]
sys.modules.setdefault("deps_test", PKG)


def _load_module(name):
    path = ADDON_ROOT / "core" / "deps" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"deps_test.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_load_module("types")
adapters = _load_module("adapters")
runtime_graph = _load_module("runtime_graph")
runtime_impact = _load_module("runtime_impact")


def _impact_sets(graph, dirty, meta):
    with patch.object(runtime_impact, "get_registered_entity_types",
                      return_value=("FIBER", "MUSCLE")):
        return runtime_impact.compute_impacted_sets(graph, dirty, meta)


def fiber(fid, a_id, b_id, touch_ids=(), topology="OPEN", loop_ids=()):
    touches = [SimpleNamespace(parent_id=value) for value in touch_ids]
    anchors = [SimpleNamespace(parent_id=value, attach_param="RAW") for value in loop_ids]
    return SimpleNamespace(id=fid, a_parent_id=a_id, b_parent_id=b_id, mid_touches=touches, topology_mode=topology, loop_anchors=anchors)


def _with_node_target(item, target_id):
    nodes = tuple(FiberNodeAttachment(target_id, "RAW", (0.0, 0.0, 0.0)) for _index in range(2))
    item.node_attachments_json = encode_node_attachments(FiberNodeAttachmentPayload(1, 2, False, nodes))
    return item


def muscle(mid, fiber_ids):
    refs = [SimpleNamespace(fiber_id=value) for value in fiber_ids]
    return SimpleNamespace(id=mid, fiber_refs=refs)


class RuntimeGraphTests(unittest.TestCase):
    def test_legacy_surface_metadata_cannot_add_scp_dependency(self):
        import json
        material = json.dumps(dict(bound_stations=[dict(nodes=[dict(target_id='S2')])]))
        surface = SimpleNamespace(id='FS1',fiber_refs=[],get=lambda key,default:material)
        native = muscle('M1',[]); native.surface_source_mode='FIBER_SURFACE'; native.fiber_surface_id='FS1'
        scps = [SimpleNamespace(id='S2',parent_id='')]
        vcp = SimpleNamespace(fibers=[],fiber_surfaces=[surface],muscles=[native],blobs=[],soft_tissues=[])
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps),af_vcp_system=vcp)
        graph = runtime_graph.RuntimeGraph(); entities = adapters.build_runtime_graph(root,graph)
        self.assertFalse({('FIBER_SURFACE','FS1'),('MUSCLE','M1')} & graph.downstream_entities({('SCP','S2')}))
        self.assertNotIn('REGION',entities)

    def test_selection_impacts_only_selected_entities(self):
        graph = runtime_graph.RuntimeGraph()
        graph.add_entity_edge(("FIBER", "F1"), ("MUSCLE", "M1"))
        dirty = {"FIBER": {"F1"}, "MUSCLE": set()}
        impacted = _impact_sets(graph, dirty, {"event_type": "SELECTION"})
        self.assertEqual((impacted["FIBER"], impacted["MUSCLE"]), ({"F1"}, set()))

    def test_fiber_update_aspect_does_not_dirty_downstream(self):
        graph = runtime_graph.RuntimeGraph()
        graph.add_entity_edge(("FIBER", "F1"), ("MUSCLE", "M1"))
        dirty = {"FIBER": {"F1"}, "MUSCLE": set()}
        meta = {"event_type": "FIBER_UPDATE", "dirty_aspects": {"FIBER": {"SOLVER"}}}
        impacted = _impact_sets(graph, dirty, meta)
        self.assertEqual((impacted["FIBER"], impacted["MUSCLE"]), ({"F1"}, set()))

    def test_solve_ready_propagates_fiber_downstream(self):
        graph = runtime_graph.RuntimeGraph()
        graph.add_entity_edge(("FIBER", "F1"), ("MUSCLE", "M1"))
        dirty = {"FIBER": {"F1"}, "MUSCLE": set()}
        impacted = _impact_sets(graph, dirty, {"event_type": "FIBER_SOLVE_READY"})
        self.assertEqual((impacted["FIBER"], impacted["MUSCLE"]), ({"F1"}, {"M1"}))

    def test_local_fiber_constraint_impact_stays_local(self):
        graph = runtime_graph.RuntimeGraph()
        graph.add_entity_edge(("FIBER", "F1"), ("MUSCLE", "M1"))
        impacted = {"FIBER": {"F1"}, "MUSCLE": set()}
        meta = {"event_type": "FIBER_UPDATE", "dirty_aspects": {"FIBER": {"ATTACHMENT"}}}
        out = runtime_impact.expand_constraint_impacts(graph, impacted, {"FIBER": {"F1"}}, meta)
        self.assertEqual((out["FIBER"], out["MUSCLE"]), ({"F1"}, set()))

    def test_runtime_graph_connects_scp_vcp_chain(self):
        scps = [SimpleNamespace(id="S1", parent_id=""), SimpleNamespace(id="S2", parent_id="S1")]
        tissue = SimpleNamespace(id="T1", host_scp_id="S2")
        vcp = SimpleNamespace(fibers=[fiber("F1", "S1", "S2")], muscles=[muscle("M1", ["F1"])],
                              blobs=[], soft_tissues=[tissue])
        vcp.blobs.append(SimpleNamespace(id="B1", attach_target_type="MUSCLE", attach_target_id="M1"))
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=vcp)
        graph = runtime_graph.RuntimeGraph()
        entity_sets = adapters.build_runtime_graph(root, graph)
        impacted = graph.downstream_entities({("SCP", "S1")})
        self.assertEqual(entity_sets["SCP"], {"S1", "S2"})
        expected = {("SCP", "S2"), ("FIBER", "F1"), ("MUSCLE", "M1"), ("BLOB", "B1"),
                    ("SOFT_TISSUE", "T1")}
        self.assertTrue(expected <= impacted)

    def test_fiber_node_surface_is_an_attachment_dependency(self):
        scps = [SimpleNamespace(id="S1", parent_id=""), SimpleNamespace(id="S2", parent_id="")]
        item = _with_node_target(fiber("F1", "S1", "S1"), "S2")
        vcp = SimpleNamespace(fibers=[item], muscles=[], fiber_surfaces=[], blobs=[], soft_tissues=[])
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=vcp)
        graph = runtime_graph.RuntimeGraph(); adapters.build_runtime_graph(root, graph)
        self.assertIn(("FIBER", "F1"), graph.downstream_entities({("SCP", "S2")}))

    def test_tarjan_scc_groups_cycle(self):
        adjacency = {"A": {"B"}, "B": {"A"}, "C": {"D"}, "D": set()}
        sccs = [set(values) for values in runtime_graph.tarjan_scc(adjacency)]
        self.assertIn({"A", "B"}, sccs)
        self.assertIn({"C"}, sccs)
        self.assertIn({"D"}, sccs)

    def test_fiber_surface_is_authoritative_dependency(self):
        scps = [SimpleNamespace(id="S1", parent_id="")]
        surface = SimpleNamespace(id="FS1", fiber_refs=[SimpleNamespace(fiber_id="F1")])
        muscle = SimpleNamespace(id="M1", fiber_refs=[SimpleNamespace(fiber_id="IGNORED")],
                                 surface_source_mode="FIBER_SURFACE", fiber_surface_id="FS1")
        tissue = SimpleNamespace(id="T1", host_scp_id="", base_source_type="FIBER_SURFACE", base_source_id="FS1")
        vcp = SimpleNamespace(fibers=[fiber("F1", "S1", "S1")], fiber_surfaces=[surface],
                              muscles=[muscle], blobs=[], soft_tissues=[tissue])
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=vcp)
        graph = runtime_graph.RuntimeGraph()
        adapters.build_runtime_graph(root, graph)
        impacted = graph.downstream_entities({("FIBER", "F1")})
        self.assertTrue({("FIBER_SURFACE", "FS1"), ("MUSCLE", "M1"), ("SOFT_TISSUE", "T1")} <= impacted)
        self.assertNotIn(("FIBER", "IGNORED"), graph.entity_adjacency())

    def test_soft_tissue_source_and_muscle_target_are_independent_edges(self):
        scps = [SimpleNamespace(id="S1", parent_id="")]
        surface = SimpleNamespace(id="FS1", fiber_refs=[])
        muscle = SimpleNamespace(id="M1", fiber_refs=[], surface_source_mode="FIBER_SURFACE", fiber_surface_id="FS1")
        tissue = SimpleNamespace(id="T1", schema_version=2, base_source_type="FIBER_SURFACE",
                                 base_source_id="FS1", attachment_target_type="MUSCLE",
                                 attachment_target_id="M1", attachment_target_surface="MUSCLE_INFL")
        vcp = SimpleNamespace(fibers=[], fiber_surfaces=[surface], muscles=[muscle], blobs=[], soft_tissues=[tissue])
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=vcp)
        graph = runtime_graph.RuntimeGraph()
        adapters.build_runtime_graph(root, graph)
        self.assertIn(("SOFT_TISSUE", "T1"), graph.downstream_entities({("FIBER_SURFACE", "FS1")}))
        self.assertIn(("SOFT_TISSUE", "T1"), graph.downstream_entities({("MUSCLE", "M1")}))
