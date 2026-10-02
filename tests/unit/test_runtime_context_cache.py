from pathlib import Path
import importlib.util
import sys
import types
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

PKG = types.ModuleType("deps_cache_test")
PKG.__path__ = [str(ADDON_ROOT / "core" / "deps")]
sys.modules.setdefault("deps_cache_test", PKG)


def _load_module(name):
    path = ADDON_ROOT / "core" / "deps" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"deps_cache_test.{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_load_module("types")
_load_module("runtime_graph")
_load_module("runtime_models")
runtime_context_build = _load_module("runtime_context_build")


class RecorderDriver:
    name = "recorder"

    def __init__(self):
        self.calls = 0

    def build_graph(self, _root, graph, entity_sets):
        self.calls += 1
        entity_sets["SCP"].add("S1")
        graph.add_entity_edge(("SCP", "S1"), ("SCP", "S2"))
        for tissue in getattr(_root.af_vcp_system, "soft_tissues", ()):
            entity_sets.setdefault("SOFT_TISSUE", set()).add(tissue.id)
            graph.add_entity_edge(("SCP", tissue.host_scp_id), ("SOFT_TISSUE", tissue.id))


def _root():
    scps = [SimpleNamespace(id="S1", parent_id=""), SimpleNamespace(id="S2", parent_id="S1")]
    vcp = SimpleNamespace(fibers=[], muscles=[], blobs=[], soft_tissues=[])
    return SimpleNamespace(af_scp_system=SimpleNamespace(scps=scps), af_vcp_system=vcp)


class RuntimeContextCacheTests(unittest.TestCase):
    def test_build_runtime_context_reuses_cached_topology(self):
        driver = RecorderDriver()
        root = _root()
        runtime_context_build.clear_runtime_context_cache()
        allow = SimpleNamespace(allow=True, filtered_ids=None)
        with patch.object(runtime_context_build, "get_dependency_drivers", return_value=[driver]), patch.object(runtime_context_build, "get_registered_entity_types", return_value=("SCP",)), patch.object(runtime_context_build, "evaluate_gates", return_value=allow):
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
        self.assertEqual(driver.calls, 1)

    def test_build_runtime_context_invalidates_cache_on_topology_change(self):
        driver = RecorderDriver()
        root = _root()
        runtime_context_build.clear_runtime_context_cache()
        allow = SimpleNamespace(allow=True, filtered_ids=None)
        with patch.object(runtime_context_build, "get_dependency_drivers", return_value=[driver]), patch.object(runtime_context_build, "get_registered_entity_types", return_value=("SCP",)), patch.object(runtime_context_build, "evaluate_gates", return_value=allow):
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
            root.af_scp_system.scps.append(SimpleNamespace(id="S3", parent_id="S2"))
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
        self.assertEqual(driver.calls, 2)

    def test_cache_invalidation_adds_new_soft_tissue_dependency(self):
        driver, root = RecorderDriver(), _root()
        runtime_context_build.clear_runtime_context_cache()
        allow = SimpleNamespace(allow=True, filtered_ids=None)
        with patch.object(runtime_context_build, "get_dependency_drivers", return_value=[driver]), patch.object(runtime_context_build, "get_registered_entity_types", return_value=("SCP", "SOFT_TISSUE")), patch.object(runtime_context_build, "evaluate_gates", return_value=allow):
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
            root.af_vcp_system.soft_tissues.append(SimpleNamespace(id="T1", host_scp_id="S1"))
            build = runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
        impacted = build.graph.downstream_entities({("SCP", "S1")})
        self.assertEqual(driver.calls, 2)
        self.assertIn(("SOFT_TISSUE", "T1"), impacted)

    def test_cache_invalidates_when_soft_target_role_changes(self):
        driver, root = RecorderDriver(), _root()
        tissue = SimpleNamespace(id="T1", schema_version=2, host_scp_id="S1", base_source_type="OBJECT",
                                 base_source_id="", attachment_target_type="MUSCLE",
                                 attachment_target_id="M1", attachment_target_surface="MUSCLE_INFL")
        root.af_vcp_system.soft_tissues.append(tissue)
        runtime_context_build.clear_runtime_context_cache()
        allow = SimpleNamespace(allow=True, filtered_ids=None)
        patches = (patch.object(runtime_context_build, "get_dependency_drivers", return_value=[driver]),
                   patch.object(runtime_context_build, "get_registered_entity_types", return_value=("SCP",)),
                   patch.object(runtime_context_build, "evaluate_gates", return_value=allow))
        with patches[0], patches[1], patches[2]:
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
            tissue.attachment_target_surface = "MUSCLE_BASE"
            runtime_context_build.build_runtime_context(root, None, {"SCP": {"S1"}})
        self.assertEqual(driver.calls, 2)
