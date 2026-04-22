import bpy

from ..core.deps.dirty_hints import dirty_hints_for, empty_dirty_hints
from ..core.utils import get_af_root
from ..core.visualization.control_runtime import notify_selection_changed


def _sync_scene(context, scp_id=None, source="property", event_type="UPDATE"):
    scene = context.scene if context else None
    root = get_af_root(scene)
    if root is None:
        return
    from ..core.visualization.sync_runner import sync_from_dirty_hints
    hints = dirty_hints_for("SCP", {scp_id}) if scp_id else empty_dirty_hints()
    sync_from_dirty_hints(root=root, scene=scene, dirty_hints=hints, source=source, event_type=event_type)


def _on_scp_prop_update(self, context):
    _sync_scene(context, getattr(self, "id", ""))


def _find_scene_scp_object(scene, root_name, scp_id):
    for obj in scene.objects:
        if obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_root_name") == root_name and obj.get("af_scp_id") == scp_id:
            return obj
    return None


def _select_only_object(scene, context, target):
    scene.af_selection_sync_lock = True
    try:
        for obj in context.selected_objects:
            obj.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
    finally:
        scene.af_selection_sync_lock = False


def _active_scp_selection_target(system_prop, context):
    scene = context.scene if context else None
    root = get_af_root(scene)
    index = int(getattr(system_prop, "active_scp_index", -1))
    if not scene or scene.af_selection_sync_lock or root is None:
        return None, scene
    if index < 0 or index >= len(system_prop.scps):
        return None, scene
    scp_id = system_prop.scps[index].id
    return _find_scene_scp_object(scene, root.name, scp_id), scene


def _on_active_scp_index_update(self, context):
    obj, scene = _active_scp_selection_target(self, context)
    if obj is None:
        return
    _select_only_object(scene, context, obj)
    notify_selection_changed(scene)


class AF_SCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="", update=_on_scp_prop_update)

    object_name: bpy.props.StringProperty(name="Object Name", default="", update=_on_scp_prop_update)
    parent_id: bpy.props.StringProperty(name="Parent ID", default="", update=_on_scp_prop_update)

    attach_follow_rotation: bpy.props.BoolProperty(name="Follow Parent Rotation", default=True, update=_on_scp_prop_update)
    attach_initialized: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    attach_parent_tri_vidx: bpy.props.IntVectorProperty(name="Attach Parent Triangle Vertex Indices", size=3, default=(-1, -1, -1), options={"HIDDEN"})
    attach_parent_tri_weights: bpy.props.FloatVectorProperty(name="Attach Parent Triangle Barycentric", size=3, default=(1.0, 0.0, 0.0), options={"HIDDEN"})
    attach_child_origin_local: bpy.props.FloatVectorProperty(name="Attach Child Origin Local", size=3, default=(0.0, 0.0, 0.0), options={"HIDDEN"})
    attach_child_tangent_local: bpy.props.FloatVectorProperty(name="Attach Child Tangent Local", size=3, default=(1.0, 0.0, 0.0), options={"HIDDEN"})
    attach_child_normal_local: bpy.props.FloatVectorProperty(name="Attach Child Normal Local", size=3, default=(0.0, 0.0, 1.0), options={"HIDDEN"})

    mirror_enabled: bpy.props.BoolProperty(name="Mirror Children", default=False, update=_on_scp_prop_update)
    mirror_axis: bpy.props.EnumProperty(
        name="Mirror Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
        update=_on_scp_prop_update,
    )
    mirror_origin: bpy.props.FloatVectorProperty(name="Mirror Origin", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0), update=_on_scp_prop_update)
    mirror_status: bpy.props.EnumProperty(
        name="Mirror Status",
        items=[
            ("NONE", "None", ""),
            ("SOURCE", "Source", ""),
            ("TARGET", "Target", ""),
        ],
        default="NONE",
        options={"HIDDEN"},
    )
    mirror_source_id: bpy.props.StringProperty(name="Mirror Source ID", default="", options={"HIDDEN"})
    mirror_effective_axis: bpy.props.EnumProperty(
        name="Mirror Effective Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
        options={"HIDDEN"},
    )


class AF_SCP_System_Property(bpy.types.PropertyGroup):
    scps: bpy.props.CollectionProperty(type=AF_SCP_Property)
    active_scp_index: bpy.props.IntProperty(default=-1, update=_on_active_scp_index_update)
