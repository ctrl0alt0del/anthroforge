from pathlib import Path
import sys
import tempfile
import unittest

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from core.id_utils import next_prefixed_id
from core.scp_runtime.object_roles import create_scp, set_scp_geometry_object, set_scp_transform_object
from core.utils import ensure_af_root


def ensure_addon_registered():
    import anthroforge
    if not hasattr(bpy.types.Object, "af_scp_system"):
        anthroforge.register()


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ensure_addon_registered()


def mesh_object(name, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1)], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def empty_object(name, location=(0.0, 0.0, 0.0)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def root():
    return ensure_af_root(bpy.context.scene)


def scp_with_object(root_obj, name, obj, with_geometry=True):
    item = create_scp(root_obj, name)
    set_scp_transform_object(root_obj, item, obj)
    set_scp_geometry_object(root_obj, item, obj if with_geometry else None)
    return item


def fiber(root_obj, a_id, b_id):
    item = root_obj.af_vcp_system.fibers.add()
    item.id = next_prefixed_id(root_obj.af_vcp_system.fibers, "FIBER")
    item.name = item.id
    item.a_parent_id = a_id
    item.b_parent_id = b_id
    return item


def capture_mesh_attachment(root_obj, scp, index):
    from core.vcp.attachment_backend import capture_attachment_from_mesh_vertex
    return capture_attachment_from_mesh_vertex(root_obj, bpy.context.scene, scp.id, index)


def capture_world_attachment(root_obj, scp_id, point):
    from core.vcp.attachment_backend import capture_attachment_from_world
    return capture_attachment_from_world(root_obj, bpy.context.scene, scp_id, point)


def select_only(obj):
    for other in tuple(bpy.context.selected_objects):
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def find_flagged(flag, entity_id=None, id_key=None):
    for obj in bpy.context.scene.objects:
        if not obj.get(flag):
            continue
        if entity_id is None or obj.get(id_key or "id") == entity_id:
            return obj
    return None


def add_shortcut(root_obj, name, owner_type, owner_id, data_path):
    item = root_obj.af_shortcut_system.shortcuts.add()
    item.id = next_prefixed_id(root_obj.af_shortcut_system.shortcuts, "SHORTCUT")
    item.name = name
    item.owner_type = owner_type
    item.owner_id = owner_id
    item.data_path = data_path
    item.owner_backsolve = False
    return item


def temp_blend_path():
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".blend")
    handle.close()
    return handle.name


class BlenderTestCase(unittest.TestCase):
    def setUp(self):
        reset_scene()
