import bpy

from ..core.utils import get_af_root


def _poll_marked_scp_source(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    return bool(root and obj and obj.type == "MESH" and obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_root_name") == root.name and obj.get("af_scp_id"))


def _poll_parent_proxy(self, obj):
    return _poll_marked_scp_source(self, obj)


def _poll_any_obj(self, obj):
    return obj is not None


def _register_scene_core_props():
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)


def _register_scene_pointer_props():
    bpy.types.Scene.af_scp_parent_obj = bpy.props.PointerProperty(name="SCP Parent", type=bpy.types.Object, poll=_poll_marked_scp_source)
    bpy.types.Scene.af_new_fiber_origin_obj = bpy.props.PointerProperty(name="Fiber Origin", type=bpy.types.Object, poll=_poll_parent_proxy)
    bpy.types.Scene.af_new_fiber_insertion_obj = bpy.props.PointerProperty(name="Fiber Insertion", type=bpy.types.Object, poll=_poll_parent_proxy)
    bpy.types.Scene.af_new_blob_target_obj = bpy.props.PointerProperty(name="Blob Target", type=bpy.types.Object, poll=_poll_any_obj)


def _register_scene_string_props():
    bpy.types.Scene.af_tree_collapsed_json = bpy.props.StringProperty(name="AF Tree Collapsed", default="{}")
    bpy.types.Scene.af_vcp_tree_collapsed_json = bpy.props.StringProperty(name="AF VCP Tree Collapsed", default="{}")


def register_scene_props():
    _register_scene_core_props()
    _register_scene_pointer_props()
    _register_scene_string_props()


def _delete_scene_prop(name):
    if hasattr(bpy.types.Scene, name):
        delattr(bpy.types.Scene, name)


def unregister_scene_props():
    for name in ("af_vcp_tree_collapsed_json", "af_tree_collapsed_json", "af_new_blob_target_obj", "af_new_fiber_insertion_obj", "af_new_fiber_origin_obj", "af_scp_parent_obj", "af_selection_sync_lock"):
        _delete_scene_prop(name)
