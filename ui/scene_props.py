import bpy

from ..core.scp_runtime.common import is_geometry_mesh_scp_obj
from ..core.utils import get_af_root


def _attachment_toggle_api():
    try:
        from ..app.use_cases.attachment_toggle import handle_attachment_toggle
    except ImportError:
        from app.use_cases.attachment_toggle import handle_attachment_toggle
    return handle_attachment_toggle


def _on_attachment_toggle_update(_self, context):
    _attachment_toggle_api()(context)


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


def _poll_soft_tissue_base(self, obj):
    return bool(obj and obj.type in {"EMPTY", "CURVE", "MESH"})


def _poll_scp_obj(self, obj):
    scene = getattr(bpy.context, "scene", None)
    root = get_af_root(scene)
    return bool(root and obj and obj.get("af_root_name") == root.name and obj.get("af_scp_id") and obj.get("af_scp_bound"))


def _register_scene_core_props():
    bpy.types.Scene.af_attachments_enabled = bpy.props.BoolProperty(name="Attachments Enabled", default=True, update=_on_attachment_toggle_update, options={"SKIP_SAVE"})
    bpy.types.Scene.af_selection_sync_lock = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.af_selection_order_json = bpy.props.StringProperty(default="[]", options={"SKIP_SAVE"})
    bpy.types.Scene.af_draft_skin_running = bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    bpy.types.Scene.af_draft_skin_progress = bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0, subtype="FACTOR", options={"SKIP_SAVE"})
    bpy.types.Scene.af_draft_skin_stage = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_draft_skin_message = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_draft_skin_diagnostic = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_topology_running = bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    bpy.types.Scene.af_topology_progress = bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0, subtype="FACTOR", options={"SKIP_SAVE"})
    bpy.types.Scene.af_topology_stage = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_topology_message = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_topology_diagnostic = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})


def _register_scene_update_props():
    bpy.types.Scene.af_warm_update_running = bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})
    bpy.types.Scene.af_warm_update_progress = bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0, subtype="FACTOR", options={"SKIP_SAVE"})
    bpy.types.Scene.af_warm_update_stage = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_warm_update_message = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_warm_update_diagnostic = bpy.props.StringProperty(default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_last_update_type = bpy.props.StringProperty(default="")
    bpy.types.Scene.af_last_update_seconds = bpy.props.FloatProperty(default=0.0, min=0.0)
    bpy.types.Scene.af_last_update_diagnostic = bpy.props.StringProperty(default="")


def _register_scene_pointer_props():
    bpy.types.Scene.af_scp_parent_obj = bpy.props.PointerProperty(name="SCP Parent", type=bpy.types.Object, poll=_poll_parent_proxy)
    bpy.types.Scene.af_scp_object_picker = bpy.props.PointerProperty(name="SCP Object", type=bpy.types.Object, poll=_poll_any_obj)
    bpy.types.Scene.af_control_scp_obj = bpy.props.PointerProperty(name="Control SCP", type=bpy.types.Object, poll=_poll_scp_obj)
    bpy.types.Scene.af_new_fiber_origin_obj = bpy.props.PointerProperty(name="Fiber Origin", type=bpy.types.Object, poll=_poll_geometry_scp_mesh)
    bpy.types.Scene.af_new_fiber_insertion_obj = bpy.props.PointerProperty(name="Fiber Insertion", type=bpy.types.Object, poll=_poll_geometry_scp_mesh)
    bpy.types.Scene.af_new_blob_target_obj = bpy.props.PointerProperty(name="Blob Target", type=bpy.types.Object, poll=_poll_any_obj)
    bpy.types.Scene.af_new_soft_tissue_base_obj = bpy.props.PointerProperty(name="Soft Tissue Base", type=bpy.types.Object, poll=_poll_soft_tissue_base)
    bpy.types.Scene.af_new_soft_tissue_host_obj = bpy.props.PointerProperty(name="Soft Tissue Host", type=bpy.types.Object, poll=_poll_geometry_scp_mesh)
    bpy.types.Scene.af_new_soft_tissue_preset = bpy.props.EnumProperty(name="Preset", items=(("CUSTOM", "Custom", ""), ("CLOSED_BULK", "Closed Bulk", ""), ("RIM", "Rim", ""), ("LAYER", "Layer", ""), ("POUCH", "Pouch", "")), default="CUSTOM")


def _register_scene_string_props():
    bpy.types.Scene.af_tree_collapsed_json = bpy.props.StringProperty(name="AF Tree Collapsed", default="{}")
    bpy.types.Scene.af_vcp_tree_collapsed_json = bpy.props.StringProperty(name="AF VCP Tree Collapsed", default="{}")


def _register_scene_action_library_props():
    bpy.types.Scene.af_action_gn_name = bpy.props.StringProperty(name="GN Name", default="AF_Loft")
    bpy.types.Scene.af_action_curve_count = bpy.props.IntProperty(name="Curve Count", default=4, min=2)
    bpy.types.Scene.af_action_single_angle = bpy.props.BoolProperty(name="Use One Angle", default=False)
    bpy.types.Scene.af_action_quick_hook_reuse = bpy.props.BoolProperty(name="Reuse Last Hook", default=False, options={"SKIP_SAVE"})


def _register_scene_shortcut_props():
    item_type = _wizard_item_type()
    bpy.types.Scene.af_new_shortcut_name = bpy.props.StringProperty(name="Shortcut Name", default="")
    bpy.types.Scene.af_new_shortcut_path = bpy.props.StringProperty(name="Data Path", default="")
    bpy.types.Scene.af_shortcut_wizard_wildcard_value = bpy.props.StringProperty(name="Wildcard Value", default="", options={"SKIP_SAVE"})
    bpy.types.Scene.af_shortcut_wizard_items = bpy.props.CollectionProperty(type=item_type, options={"SKIP_SAVE"})
    bpy.types.Scene.af_shortcut_wizard_active_index = bpy.props.IntProperty(default=-1, options={"SKIP_SAVE"})
    bpy.types.Scene.af_shortcut_view_mode = bpy.props.EnumProperty(
        name="Shortcut View",
        items=(("SELECTED", "Selected", ""), ("ALL", "All", "")),
        default="SELECTED",
    )


def _wizard_item_type():
    try:
        from ..properties.shortcut_properties import AF_ShortcutWizardItem_Property
    except ImportError:
        from properties.shortcut_properties import AF_ShortcutWizardItem_Property
    return AF_ShortcutWizardItem_Property


def register_scene_props():
    _register_scene_core_props()
    _register_scene_update_props()
    _register_scene_pointer_props()
    _register_scene_string_props()
    _register_scene_action_library_props()
    _register_scene_shortcut_props()


def _delete_scene_prop(name):
    if hasattr(bpy.types.Scene, name):
        delattr(bpy.types.Scene, name)


def unregister_scene_props():
    for name in ("af_last_update_diagnostic", "af_last_update_seconds", "af_last_update_type", "af_warm_update_diagnostic", "af_warm_update_message", "af_warm_update_stage", "af_warm_update_progress", "af_warm_update_running", "af_topology_diagnostic", "af_topology_message", "af_topology_stage", "af_topology_progress", "af_topology_running", "af_draft_skin_diagnostic", "af_draft_skin_message", "af_draft_skin_stage", "af_draft_skin_progress", "af_draft_skin_running", "af_shortcut_wizard_active_index", "af_shortcut_wizard_items", "af_shortcut_wizard_wildcard_value", "af_shortcut_view_mode", "af_new_shortcut_path", "af_new_shortcut_name", "af_action_quick_hook_reuse", "af_action_single_angle", "af_action_curve_count", "af_action_gn_name", "af_vcp_tree_collapsed_json", "af_tree_collapsed_json", "af_new_soft_tissue_preset", "af_new_soft_tissue_host_obj", "af_new_soft_tissue_base_obj", "af_new_blob_target_obj", "af_new_fiber_insertion_obj", "af_new_fiber_origin_obj", "af_control_scp_obj", "af_scp_object_picker", "af_scp_parent_obj", "af_selection_order_json", "af_selection_sync_lock", "af_attachments_enabled"):
        _delete_scene_prop(name)
