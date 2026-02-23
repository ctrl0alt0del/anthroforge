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


def register_scene_props():
    bpy.types.Scene.af_scp_type = bpy.props.EnumProperty(
        name="SCP Type",
        items=lambda self, context: ShapeRegistry.enum_items(),
    )
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.af_new_parent_obj = bpy.props.PointerProperty(
        name="Parent",
        type=bpy.types.Object,
        poll=_poll_parent_proxy,
    )

    bpy.types.Scene.af_new_fiber_origin_obj = bpy.props.PointerProperty(
        name="Fiber Origin",
        type=bpy.types.Object,
        poll=_poll_parent_proxy,
    )
    bpy.types.Scene.af_new_fiber_insertion_obj = bpy.props.PointerProperty(
        name="Fiber Insertion",
        type=bpy.types.Object,
        poll=_poll_parent_proxy,
    )

    bpy.types.Scene.af_tree_collapsed_json = bpy.props.StringProperty(
        name="AF Tree Collapsed",
        default="{}",
    )

    # NEW: separate collapse state for VCP tree
    bpy.types.Scene.af_vcp_tree_collapsed_json = bpy.props.StringProperty(
        name="AF VCP Tree Collapsed",
        default="{}",
    )

    ShapeRegistry.register_scene_props()


def unregister_scene_props():
    ShapeRegistry.unregister_scene_props()

    del bpy.types.Scene.af_vcp_tree_collapsed_json
    del bpy.types.Scene.af_tree_collapsed_json
    del bpy.types.Scene.af_new_fiber_insertion_obj
    del bpy.types.Scene.af_new_fiber_origin_obj
    del bpy.types.Scene.af_new_parent_obj
    del bpy.types.Scene.af_selection_sync_lock
    del bpy.types.Scene.af_scp_type
