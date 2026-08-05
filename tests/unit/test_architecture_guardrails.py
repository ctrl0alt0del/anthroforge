from pathlib import Path
import importlib.util
import sys
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)


def _load_tool(name):
    path = ADDON_ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SIZE = _load_tool("check_scp_function_size.py")
CONTEXT = _load_tool("check_core_context_usage.py")
CONTRACT_DOC = ADDON_ROOT / "docs" / "runtime_contract.md"


class ArchitectureGuardrailTests(unittest.TestCase):
    def test_runtime_contract_doc_lists_required_runtime_metadata(self):
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        for token in ("dirty_hints", "source", "event_type", "scp_recapture_ids", "scp_apply_target_ids", "scp_apply_parent_ids", "non_source_ids_by_type", "_PENDING", "_TIMER_ARMED"):
            self.assertIn(token, text)

    def test_function_size_ratchet_has_no_new_or_grown_violations(self):
        status = SIZE.ratchet_status()
        self.assertEqual(status["new"], [])
        self.assertEqual(status["grown"], [])

    def test_core_context_boundary_has_no_new_usages(self):
        status = CONTEXT.ratchet_status()
        self.assertEqual(status["new"], {})

    def test_draft_skin_core_is_blender_independent(self):
        folder = ADDON_ROOT / "core" / "draft_skin"
        offenders = [
            path.name for path in folder.glob("*.py")
            if "import bpy" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_topology_core_is_blender_independent(self):
        folder = ADDON_ROOT / "core" / "topology"
        offenders = [path.name for path in folder.glob("*.py")
                     if "import bpy" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_warm_start_core_is_blender_independent(self):
        folder = ADDON_ROOT / "core" / "warm_start"
        offenders = [path.name for path in folder.glob("*.py")
                     if "import bpy" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])
