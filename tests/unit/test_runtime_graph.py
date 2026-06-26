from pathlib import Path
import importlib.util
import sys
import types
import unittest
from types import SimpleNamespace

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path

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


def fiber(fid, a_id, b_id, touch_ids=(), topology="OPEN", generation="SOLVED", driver_id="", loop_ids=()):
    touches = [SimpleNamespace(parent_id=value) for value in touch_ids]
    anchors = [SimpleNamespace(parent_id=value, attach_param="RAW") for value in loop_ids]
    return SimpleNamespace(id=fid, a_parent_id=a_id, b_parent_id=b_id, mid_touches=touches, topology_mode=topology, generation_mode=generation, driver_fiber_id=driver_id, loop_anchors=anchors)


def muscle(mid, fiber_ids):
    refs = [SimpleNamespace(fiber_id=value) for value in fiber_ids]
    return SimpleNamespace(id=mid, fiber_refs=refs)


class RuntimeGraphTests(unittest.TestCase):
    def test_runtime_graph_connects_scp_vcp_chain(self):
        scps = [SimpleNamespace(id="S1", parent_id=""), SimpleNamespace(id="S2", parent_id="S1")]
        vcp = SimpleNamespace(fibers=[fiber("F1", "S1", "S2")], muscles=[muscle("M1", ["F1"])], blobs=[])
        vcp.blobs.append(SimpleNamespace(id="B1", attach_target_type="MUSCLE", attach_target_id="M1"))
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=vcp)
        graph = runtime_graph.RuntimeGraph()
        entity_sets = adapters.build_runtime_graph(root, graph)
        impacted = graph.downstream_entities({("SCP", "S1")})
        self.assertEqual(entity_sets["SCP"], {"S1", "S2"})
        self.assertTrue({("SCP", "S2"), ("FIBER", "F1"), ("MUSCLE", "M1"), ("BLOB", "B1")} <= impacted)

    def test_tarjan_scc_groups_cycle(self):
        adjacency = {"A": {"B"}, "B": {"A"}, "C": {"D"}, "D": set()}
        sccs = [set(values) for values in runtime_graph.tarjan_scc(adjacency)]
        self.assertIn({"A", "B"}, sccs)
        self.assertIn({"C"}, sccs)
        self.assertIn({"D"}, sccs)

    def test_runtime_graph_links_solved_loop_driver_to_derived_loop(self):
        scps = [SimpleNamespace(id="S1", parent_id=""), SimpleNamespace(id="S2", parent_id=""), SimpleNamespace(id="S3", parent_id="")]
        fibers = [fiber("F1", "", "", topology="LOOP", loop_ids=("S1", "S2", "S3")), fiber("F2", "", "", topology="LOOP", generation="DERIVED", driver_id="F1")]
        root = SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=SimpleNamespace(fibers=fibers, muscles=[], blobs=[]))
        graph = runtime_graph.RuntimeGraph()
        adapters.build_runtime_graph(root, graph)
        self.assertIn(("FIBER", "F2"), graph.downstream_entities({("FIBER", "F1")}))
