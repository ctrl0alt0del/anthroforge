import bpy

from ..core.scp_runtime.common import is_geometry_mesh_scp_obj
from ..core.utils import get_af_root


def _poll_geometry_scp_mesh(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    return bool(root and is_geometry_mesh_scp_obj(obj, root.name))


def _poll_parent_proxy(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    valid = root and obj and obj.get("af_root_name") == root.name and obj.get("af_scp_id")
    return bool(valid and obj.get("af_scp_bound") and obj.get("af_scp_transform"))


def _poll_any_obj(self, obj):
    return obj is not None


def _poll_scp_obj(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    return bool(root and obj and obj.get("af_root_name") == root.name and obj.get("af_scp_id") and obj.get("af_scp_bound"))


def _register_scene_core_props():
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)


def _register_scene_pointer_props():
    bpy.types.Scene.af_scp_parent_obj = bpy.props.PointerProperty(name="SCP Parent", type=bpy.types.Object, poll=_poll_parent_proxy)
    bpy.types.Scene.af_scp_object_picker = bpy.props.PointerProperty(name="SCP Object", type=bpy.types.Object, poll=_poll_any_obj)
    bpy.types.Scene.af_control_scp_obj = bpy.props.PointerProperty(name="Control SCP", type=bpy.types.Object, poll=_poll_scp_obj)
    bpy.types.Scene.af_new_fiber_origin_obj = bpy.props.PointerProperty(name="Fiber Origin", type=bpy.types.Object, poll=_poll_geometry_scp_mesh)
    bpy.types.Scene.af_new_fiber_insertion_obj = bpy.props.PointerProperty(name="Fiber Insertion", type=bpy.types.Object, poll=_poll_geometry_scp_mesh)
    bpy.types.Scene.af_new_blob_target_obj = bpy.props.PointerProperty(name="Blob Target", type=bpy.types.Object, poll=_poll_any_obj)


def _register_scene_string_props():
    bpy.types.Scene.af_tree_collapsed_json = bpy.props.StringProperty(name="AF Tree Collapsed", default="{}")
    bpy.types.Scene.af_vcp_tree_collapsed_json = bpy.props.StringProperty(name="AF VCP Tree Collapsed", default="{}")


def _register_scene_shortcut_props():
    bpy.types.Scene.af_new_shortcut_name = bpy.props.StringProperty(name="Shortcut Name", default="")
    bpy.types.Scene.af_new_shortcut_path = bpy.props.StringProperty(name="Data Path", default="")
    bpy.types.Scene.af_shortcut_view_mode = bpy.props.EnumProperty(
        name="Shortcut View",
        items=(("SELECTED", "Selected", ""), ("ALL", "All", "")),
        default="SELECTED",
    )


def register_scene_props():
    _register_scene_core_props()
    _register_scene_pointer_props()
    _register_scene_string_props()
    _register_scene_shortcut_props()


def _delete_scene_prop(name):
    if hasattr(bpy.types.Scene, name):
        delattr(bpy.types.Scene, name)


def unregister_scene_props():
    for name in ("af_shortcut_view_mode", "af_new_shortcut_path", "af_new_shortcut_name", "af_vcp_tree_collapsed_json", "af_tree_collapsed_json", "af_new_blob_target_obj", "af_new_fiber_insertion_obj", "af_new_fiber_origin_obj", "af_control_scp_obj", "af_scp_object_picker", "af_scp_parent_obj", "af_selection_sync_lock"):
        _delete_scene_prop(name)
