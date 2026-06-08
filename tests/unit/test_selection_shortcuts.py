from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _support import ensure_import_path, install_fake_modules

ensure_import_path()
bpy = install_fake_modules()

from core.selection import get_active_af_entity
from core.shortcuts import normalize_shortcut_path, resolve_shortcut


class FakeObject(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name
        self.rna_type = SimpleNamespace(properties={})

    def path_resolve(self, _path):
        return self


def scp(sid, bound=()):
    return SimpleNamespace(id=sid, bound_objects=list(bound))


def root(active_scp=0, active_type="NONE", active_id="", scps=()):
    scp_sys = SimpleNamespace(active_scp_index=active_scp, scps=list(scps))
    vcp_sys = SimpleNamespace(active_vcp_type=active_type, active_vcp_id=active_id)
    return SimpleNamespace(name="ROOT", af_scp_system=scp_sys, af_vcp_system=vcp_sys)


class SelectionShortcutTests(unittest.TestCase):
    def test_active_entity_prefers_direct_control_object(self):
        obj = FakeObject("ctrl", af_root_name="ROOT", af_fiber_endpoint_handle=True, af_fiber_id="F1")
        context = SimpleNamespace(active_object=obj)
        self.assertEqual(get_active_af_entity(root(scps=[scp("S1")]), context), ("FIBER", "F1"))

    def test_active_entity_falls_back_to_tree_state(self):
        context = SimpleNamespace(active_object=None)
        self.assertEqual(get_active_af_entity(root(active_type="BLOB", active_id="B2"), context), ("BLOB", "B2"))

    def test_normalize_shortcut_path_rewrites_bound_object_path(self):
        obj = FakeObject("bound", af_root_name="ROOT", af_scp_id="S1")
        entry = SimpleNamespace(id="OBJ_1", object_ref=obj)
        context = SimpleNamespace(active_object=None, scene=SimpleNamespace())
        bpy.data.objects[obj.name] = obj
        value = normalize_shortcut_path(root(scps=[scp("S1", [entry])]), context, 'bpy.data.objects["bound"].location[1]')
        self.assertEqual(value, 'bpy.data.objects["bound"].location[1]')

    def test_resolve_shortcut_returns_owner_and_index(self):
        obj = FakeObject("bound")
        obj.rna_type.properties["location"] = SimpleNamespace(type="FLOAT", array_length=3)
        bpy.data.objects[obj.name] = obj
        context = SimpleNamespace(active_object=None, scene=SimpleNamespace())
        target = resolve_shortcut(root(scps=[scp("S1")]), context, "af://object_rna/bound/location[1]")
        self.assertIs(target.owner, obj)
        self.assertEqual((target.prop_name, target.index), ("location", 1))

    def test_resolve_custom_property_array_shortcut(self):
        obj = FakeObject("bound", weights=[0.1, 0.2, 0.3])
        bpy.data.objects[obj.name] = obj
        context = SimpleNamespace(active_object=None, scene=SimpleNamespace())
        target = resolve_shortcut(root(scps=[scp("S1")]), context, 'af://object_rna/bound/["weights"][1]')
        self.assertEqual((target.owner, target.prop_name, target.index), (obj, '["weights"]', 1))

    def test_resolve_custom_property_reports_out_of_range_index(self):
        obj = FakeObject("bound", weights=[0.1])
        bpy.data.objects[obj.name] = obj
        context = SimpleNamespace(active_object=None, scene=SimpleNamespace())
        target = resolve_shortcut(root(scps=[scp("S1")]), context, 'af://object_rna/bound/["weights"][2]')
        self.assertEqual(target.error, "Array index is out of range.")
