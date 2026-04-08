import bpy
from ..core.utils import get_af_root
from ..core.shapes.registry import ShapeRegistry


def _poll_parent_proxy(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    if not root:
        return False
    return bool(
        obj
        and obj.get("af_proxy")
        and obj.get("af_root_name") == root.name
        and obj.get("af_scp_id")
    )


def _poll_any_mesh_obj(self, obj):
    return bool(obj and obj.type == "MESH" and obj.data is not None)


def _poll_any_obj(self, obj):
    return obj is not None


def _register_scene_core_props():
    bpy.types.Scene.af_scp_type = bpy.props.EnumProperty(
        name="SCP Type",
        items=lambda self, context: ShapeRegistry.enum_items(),
    )
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)


def _register_scene_pointer_props():
    bpy.types.Scene.af_new_parent_obj = bpy.props.PointerProperty(
        name="Parent", type=bpy.types.Object, poll=_poll_parent_proxy
    )
    bpy.types.Scene.af_new_fiber_origin_obj = bpy.props.PointerProperty(
        name="Fiber Origin", type=bpy.types.Object, poll=_poll_parent_proxy
    )
    bpy.types.Scene.af_new_fiber_insertion_obj = bpy.props.PointerProperty(
        name="Fiber Insertion", type=bpy.types.Object, poll=_poll_parent_proxy
    )
    bpy.types.Scene.af_new_blob_target_obj = bpy.props.PointerProperty(
        name="Blob Target", type=bpy.types.Object, poll=_poll_any_obj
    )
    bpy.types.Scene.af_new_scp_source_mesh_obj = bpy.props.PointerProperty(
        name="Source Mesh", type=bpy.types.Object, poll=_poll_any_mesh_obj
    )


def _register_scene_string_props():
    bpy.types.Scene.af_new_scp_mesh_asset_id = bpy.props.StringProperty(name="Mesh Asset", default="")
    bpy.types.Scene.af_tree_collapsed_json = bpy.props.StringProperty(name="AF Tree Collapsed", default="{}")
    bpy.types.Scene.af_vcp_tree_collapsed_json = bpy.props.StringProperty(
        name="AF VCP Tree Collapsed", default="{}"
    )


def register_scene_props():
    _register_scene_core_props()
    _register_scene_pointer_props()
    _register_scene_string_props()
    ShapeRegistry.register_scene_props()


def unregister_scene_props():
    ShapeRegistry.unregister_scene_props()

    if hasattr(bpy.types.Scene, "af_vcp_tree_collapsed_json"):
        del bpy.types.Scene.af_vcp_tree_collapsed_json
    if hasattr(bpy.types.Scene, "af_tree_collapsed_json"):
        del bpy.types.Scene.af_tree_collapsed_json
    if hasattr(bpy.types.Scene, "af_new_scp_mesh_asset_id"):
        del bpy.types.Scene.af_new_scp_mesh_asset_id
    if hasattr(bpy.types.Scene, "af_new_scp_source_mesh_obj"):
        del bpy.types.Scene.af_new_scp_source_mesh_obj
    if hasattr(bpy.types.Scene, "af_new_blob_target_obj"):
        del bpy.types.Scene.af_new_blob_target_obj
    if hasattr(bpy.types.Scene, "af_new_fiber_insertion_obj"):
        del bpy.types.Scene.af_new_fiber_insertion_obj
    if hasattr(bpy.types.Scene, "af_new_fiber_origin_obj"):
        del bpy.types.Scene.af_new_fiber_origin_obj
    if hasattr(bpy.types.Scene, "af_new_parent_obj"):
        del bpy.types.Scene.af_new_parent_obj
    if hasattr(bpy.types.Scene, "af_selection_sync_lock"):
        del bpy.types.Scene.af_selection_sync_lock
    if hasattr(bpy.types.Scene, "af_scp_type"):
        del bpy.types.Scene.af_scp_type
