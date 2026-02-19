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
        items=lambda self, context: ShapeRegistry.enum_items()
    )
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.af_new_parent_obj = bpy.props.PointerProperty(
        name="Parent",
        type=bpy.types.Object,
        poll=_poll_parent_proxy
    )

    # shape-specific create-form props
    ShapeRegistry.register_scene_props()


def unregister_scene_props():
    ShapeRegistry.unregister_scene_props()

    del bpy.types.Scene.af_new_parent_obj
    del bpy.types.Scene.af_selection_sync_lock
    del bpy.types.Scene.af_scp_type
