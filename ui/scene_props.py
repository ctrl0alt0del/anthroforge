import bpy

from ..core.utils import get_af_root


def _poll_marked_scp_source(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    if root is None or obj is None:
        return False
    return bool(
        obj.type == "MESH"
        and obj.get("af_scp")
        and not obj.get("af_scp_mirror")
        and obj.get("af_root_name") == root.name
        and obj.get("af_scp_id")
    )


def _poll_parent_proxy(self, obj):
    return _poll_marked_scp_source(self, obj)


def _poll_any_obj(self, obj):
    return obj is not None


def _register_scene_core_props():
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)


def _register_scene_pointer_props():
    # New SCP parent assignment UI (source-object based SCP).
    bpy.types.Scene.af_scp_parent_obj = bpy.props.PointerProperty(
        name="SCP Parent",
        type=bpy.types.Object,
        poll=_poll_marked_scp_source,
    )

    # Existing VCP creation props.
    bpy.types.Scene.af_new_fiber_origin_obj = bpy.props.PointerProperty(
        name="Fiber Origin", type=bpy.types.Object, poll=_poll_parent_proxy
    )
    bpy.types.Scene.af_new_fiber_insertion_obj = bpy.props.PointerProperty(
        name="Fiber Insertion", type=bpy.types.Object, poll=_poll_parent_proxy
    )
    bpy.types.Scene.af_new_blob_target_obj = bpy.props.PointerProperty(
        name="Blob Target", type=bpy.types.Object, poll=_poll_any_obj
    )


def _register_scene_string_props():
    bpy.types.Scene.af_tree_collapsed_json = bpy.props.StringProperty(name="AF Tree Collapsed", default="{}")
    bpy.types.Scene.af_vcp_tree_collapsed_json = bpy.props.StringProperty(
        name="AF VCP Tree Collapsed", default="{}"
    )


def register_scene_props():
    _register_scene_core_props()
    _register_scene_pointer_props()
    _register_scene_string_props()


def unregister_scene_props():
    if hasattr(bpy.types.Scene, "af_vcp_tree_collapsed_json"):
        del bpy.types.Scene.af_vcp_tree_collapsed_json
    if hasattr(bpy.types.Scene, "af_tree_collapsed_json"):
        del bpy.types.Scene.af_tree_collapsed_json
    if hasattr(bpy.types.Scene, "af_new_blob_target_obj"):
        del bpy.types.Scene.af_new_blob_target_obj
    if hasattr(bpy.types.Scene, "af_new_fiber_insertion_obj"):
        del bpy.types.Scene.af_new_fiber_insertion_obj
    if hasattr(bpy.types.Scene, "af_new_fiber_origin_obj"):
        del bpy.types.Scene.af_new_fiber_origin_obj
    if hasattr(bpy.types.Scene, "af_scp_parent_obj"):
        del bpy.types.Scene.af_scp_parent_obj
    if hasattr(bpy.types.Scene, "af_selection_sync_lock"):
        del bpy.types.Scene.af_selection_sync_lock
