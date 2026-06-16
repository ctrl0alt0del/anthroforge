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

from app.use_cases import shortcut_wizard
from core.shortcuts.wizard_scan import collect_shortcut_fields


class FakeProp:
    def __init__(self, identifier, name, prop_type="FLOAT", array_length=0, subtype="", is_readonly=False, is_hidden=False):
        self.identifier = identifier
        self.name = name
        self.type = prop_type
        self.array_length = array_length
        self.subtype = subtype
        self.is_readonly = is_readonly
        self.is_hidden = is_hidden


class FakeModifier(dict):
    def __init__(self, name, props=None, ui_data=None, mod_type="BEVEL", node_group=None, **custom):
        super().__init__(custom)
        self.name = name
        self.type = mod_type
        self.node_group = node_group
        self.rna_type = SimpleNamespace(properties={prop.identifier: prop for prop in tuple(props or ())})
        self._ui_data = dict(ui_data or {})

    def id_properties_ui(self, key):
        return SimpleNamespace(as_dict=lambda: dict(self._ui_data.get(key, {})))


class FakeObject(dict):
    def __init__(self, name, modifiers=None, ui_data=None, **custom):
        super().__init__(custom)
        self.name = name
        self.modifiers = list(modifiers or ())
        self._ui_data = dict(ui_data or {})
        self.rna_type = SimpleNamespace(properties={})

    def id_properties_ui(self, key):
        return SimpleNamespace(as_dict=lambda: dict(self._ui_data.get(key, {})))


class FakeNoIdPropModifier:
    def __init__(self, name, props=None):
        self.name = name
        self.type = "SUBSURF"
        self.node_group = None
        self.rna_type = SimpleNamespace(properties={prop.identifier: prop for prop in tuple(props or ())})

    def keys(self):
        raise TypeError("this type doesn't support IDProperties")

    def get(self, _key):
        raise TypeError("this type doesn't support IDProperties")


class FakeShortcutCollection(list):
    def add(self):
        item = SimpleNamespace(id="", name="", owner_type="", owner_id="", data_path="", vector_mode="DEFAULT")
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)


class FakeWizardCollection(list):
    def add(self):
        item = SimpleNamespace(enabled=False, label="", data_path="", shortcut_id="", shortcut_name="", vector_mode="DEFAULT")
        self.append(item)
        return item

    def remove(self, index):
        self.pop(index)


class ShortcutWizardTests(unittest.TestCase):
    def setUp(self):
        bpy.data.objects.clear()

    def test_collect_shortcut_fields_includes_transforms_modifiers_and_custom_props(self):
        mod = FakeModifier("Bevel", props=[FakeProp("width", "Width"), FakeProp("offset", "Offset", array_length=3, subtype="XYZ")], ui_data={"Arc Angle": {"subtype": "ANGLE"}}, **{"Arc Angle": 1.0})
        obj = FakeObject("Cube", modifiers=[mod], ui_data={"Spin": {"subtype": "ANGLE"}}, Spin=2.0, Axis=[1.0, 2.0, 3.0])
        fields = {(field.label, field.data_path) for field in collect_shortcut_fields(obj)}
        self.assertIn(("Location X", 'bpy.data.objects["Cube"].location[0]'), fields)
        self.assertIn(("Location Uniform", 'bpy.data.objects["Cube"].location'), fields)
        self.assertIn(("Rotation Z", 'bpy.data.objects["Cube"].rotation_euler[2]'), fields)
        self.assertIn(("Bevel: Width", 'bpy.data.objects["Cube"].modifiers["Bevel"].width'), fields)
        self.assertIn(("Bevel: Offset Y", 'bpy.data.objects["Cube"].modifiers["Bevel"].offset[1]'), fields)
        self.assertIn(("Bevel: Offset Uniform", 'bpy.data.objects["Cube"].modifiers["Bevel"].offset'), fields)
        self.assertIn(("Spin", 'bpy.data.objects["Cube"]["Spin"]'), fields)
        names = {field.label: field.default_name for field in collect_shortcut_fields(obj)}
        self.assertEqual(names["Location X"], "* Location X")
        self.assertEqual(names["Location Uniform"], "* Location Uniform")
        self.assertEqual(names["Bevel: Width"], "* Width")
        self.assertEqual(names["Bevel: Offset Y"], "* Offset Y")
        self.assertEqual(names["Bevel: Offset Uniform"], "* Offset Uniform")
        self.assertEqual(names["Spin"], "* Spin")

    def test_collect_shortcut_fields_uses_geometry_nodes_socket_names(self):
        items = [SimpleNamespace(identifier="Socket_0", name="Radius", item_type="SOCKET", in_out="INPUT"), SimpleNamespace(identifier="Socket_1", name="Twist", item_type="SOCKET", in_out="INPUT")]
        group = SimpleNamespace(interface=SimpleNamespace(items_tree=items))
        mod = FakeModifier("GeometryNodes", mod_type="NODES", node_group=group, **{"Socket_0": 1.0, "Socket_0_use_attribute": 0, "Socket_1": 2.0})
        obj = FakeObject("Cube", modifiers=[mod])
        fields = {(field.label, field.data_path) for field in collect_shortcut_fields(obj)}
        names = {field.label: field.default_name for field in collect_shortcut_fields(obj)}
        self.assertIn(("GeometryNodes: Radius", 'bpy.data.objects["Cube"].modifiers["GeometryNodes"]["Socket_0"]'), fields)
        self.assertIn(("GeometryNodes: Twist", 'bpy.data.objects["Cube"].modifiers["GeometryNodes"]["Socket_1"]'), fields)
        self.assertNotIn(("GeometryNodes: Socket_0_use_attribute", 'bpy.data.objects["Cube"].modifiers["GeometryNodes"]["Socket_0_use_attribute"]'), fields)
        self.assertEqual(names["GeometryNodes: Radius"], "* Radius")

    def test_collect_shortcut_fields_skips_modifiers_without_idproperties(self):
        mod = FakeNoIdPropModifier("Subdivision", props=[FakeProp("levels", "Levels", prop_type="INT")])
        obj = FakeObject("Cube", modifiers=[mod])
        fields = {(field.label, field.data_path) for field in collect_shortcut_fields(obj)}
        self.assertIn(("Subdivision: Levels", 'bpy.data.objects["Cube"].modifiers["Subdivision"].levels'), fields)

    def test_populate_shortcut_wizard_marks_existing_rows(self):
        item = SimpleNamespace(id="K1", name="Existing", owner_type="SCP", owner_id="S1", data_path='af://object_rna/Cube/location[0]', vector_mode="DEFAULT")
        root = SimpleNamespace(af_shortcut_system=SimpleNamespace(shortcuts=[item]), af_scp_system=SimpleNamespace(scps=[SimpleNamespace(id="S1", name="Spine")]))
        scene = SimpleNamespace(af_shortcut_wizard_items=FakeWizardCollection(), af_shortcut_wizard_active_index=-1, af_shortcut_wizard_wildcard_value="")
        obj = SimpleNamespace(name="Cube")
        bpy.data.objects[obj.name] = obj
        ctx = SimpleNamespace(scene=scene, active_object=obj)
        field = SimpleNamespace(label="Location X", data_path='bpy.data.objects["Cube"].location[0]', default_name="Location X")
        with patch("app.use_cases.shortcut_wizard.root_for_context", return_value=root):
            with patch("app.use_cases.shortcut_wizard.current_shortcut_owner", return_value=("SCP", "S1")):
                with patch("app.use_cases.shortcut_wizard.collect_shortcut_fields", return_value=(field,)):
                    with patch("app.use_cases.shortcut_wizard.normalize_shortcut_path", return_value='af://object_rna/Cube/location[0]'):
                        self.assertEqual(shortcut_wizard.populate_shortcut_wizard(ctx), (True, ""))
        row = scene.af_shortcut_wizard_items[0]
        self.assertEqual((row.enabled, row.shortcut_id, row.shortcut_name), (True, "K1", "Existing"))
        self.assertEqual(scene.af_shortcut_wizard_wildcard_value, "Spine")

    def test_apply_shortcut_wizard_creates_updates_and_deletes_rows(self):
        shortcuts = FakeShortcutCollection([
            SimpleNamespace(id="K1", name="Old", owner_type="SCP", owner_id="S1", data_path="P1", vector_mode="DEFAULT"),
            SimpleNamespace(id="K2", name="Drop", owner_type="SCP", owner_id="S1", data_path="P2", vector_mode="DEFAULT"),
        ])
        items = FakeWizardCollection([
            SimpleNamespace(enabled=True, label="Keep", data_path="P1N", shortcut_id="K1", shortcut_name="Renamed", vector_mode="DEFAULT"),
            SimpleNamespace(enabled=False, label="Drop", data_path="P2", shortcut_id="K2", shortcut_name="Drop", vector_mode="DEFAULT"),
            SimpleNamespace(enabled=True, label="Add", data_path="P3", shortcut_id="", shortcut_name="New", vector_mode="UNIFORM"),
        ])
        root = SimpleNamespace(af_shortcut_system=SimpleNamespace(shortcuts=shortcuts))
        scene = SimpleNamespace(af_shortcut_wizard_items=items, af_shortcut_wizard_active_index=2, af_shortcut_wizard_wildcard_value="")
        ctx = SimpleNamespace(scene=scene, active_object=None)
        with patch("app.use_cases.shortcut_wizard.root_for_context", return_value=root):
            with patch("app.use_cases.shortcut_wizard.current_shortcut_owner", return_value=("SCP", "S1")):
                with patch("app.use_cases.shortcut_wizard.next_prefixed_id", return_value="SHORTCUT_3"):
                    self.assertEqual(shortcut_wizard.apply_shortcut_wizard(ctx), (True, ""))
        data = {(item.id, item.name, item.data_path, item.owner_id, item.vector_mode) for item in shortcuts}
        self.assertEqual(data, {("K1", "Renamed", "P1N", "S1", "DEFAULT"), ("SHORTCUT_3", "New", "P3", "S1", "UNIFORM")})
        self.assertEqual((len(scene.af_shortcut_wizard_items), scene.af_shortcut_wizard_active_index, scene.af_shortcut_wizard_wildcard_value), (0, -1, ""))

    def test_apply_shortcut_wizard_expands_wildcard_in_names(self):
        root = SimpleNamespace(af_shortcut_system=SimpleNamespace(shortcuts=FakeShortcutCollection()))
        items = FakeWizardCollection([SimpleNamespace(enabled=True, label="Angle", data_path="P", shortcut_id="", shortcut_name="Pubis * Angle")])
        scene = SimpleNamespace(af_shortcut_wizard_items=items, af_shortcut_wizard_active_index=0, af_shortcut_wizard_wildcard_value="Arc")
        ctx = SimpleNamespace(scene=scene, active_object=None)
        with patch("app.use_cases.shortcut_wizard.root_for_context", return_value=root):
            with patch("app.use_cases.shortcut_wizard.current_shortcut_owner", return_value=("SCP", "S1")):
                with patch("app.use_cases.shortcut_wizard.next_prefixed_id", return_value="SHORTCUT_1"):
                    self.assertEqual(shortcut_wizard.apply_shortcut_wizard(ctx), (True, ""))
        data = {(item.id, item.name) for item in root.af_shortcut_system.shortcuts}
        self.assertEqual(data, {("SHORTCUT_1", "Pubis Arc Angle")})

    def test_apply_shortcut_wizard_requires_names_for_enabled_rows(self):
        root = SimpleNamespace(af_shortcut_system=SimpleNamespace(shortcuts=FakeShortcutCollection()))
        scene = SimpleNamespace(af_shortcut_wizard_items=FakeWizardCollection([SimpleNamespace(enabled=True, label="Angle", data_path="P", shortcut_id="", shortcut_name="")]), af_shortcut_wizard_active_index=0, af_shortcut_wizard_wildcard_value="")
        ctx = SimpleNamespace(scene=scene, active_object=None)
        with patch("app.use_cases.shortcut_wizard.root_for_context", return_value=root):
            with patch("app.use_cases.shortcut_wizard.current_shortcut_owner", return_value=("SCP", "S1")):
                self.assertEqual(shortcut_wizard.apply_shortcut_wizard(ctx), (False, "Shortcut name is required for Angle."))


if __name__ == "__main__":
    unittest.main()
