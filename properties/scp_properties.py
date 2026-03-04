import bpy
from mathutils import Euler, Quaternion
from ..core.utils import get_af_root


def _sync_scene(context):
    from ..core.visualization.sync_runner import sync_all
    scene = context.scene if context else None
    root = get_af_root(scene)
    sync_all(root=root, scene=scene)


def _on_scp_prop_update(self, context):
    _sync_scene(context)


def _on_euler_update(self, context):
    e = Euler(self.local_rotation_euler, "XYZ")
    q = e.to_quaternion()
    self.local_rotation = (q.w, q.x, q.y, q.z)
    _sync_scene(context)


def _on_quat_update(self, context):
    q = Quaternion(self.local_rotation)
    e = q.to_euler("XYZ")
    self["local_rotation_euler"] = (e.x, e.y, e.z)
    _sync_scene(context)


def _on_active_scp_index_update(self, context):
    scene = context.scene if context else None
    if not scene or scene.af_selection_sync_lock:
        return

    root = get_af_root(scene)
    if root is None:
        return

    idx = self.active_scp_index
    if idx < 0 or idx >= len(self.scps):
        return

    scp_id = self.scps[idx].id
    proxy = None
    for obj in scene.objects:
        if not obj.get("af_proxy"):
            continue
        if obj.get("af_mirror_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        if obj.get("af_scp_id") != scp_id:
            continue
        proxy = obj
        break

    if proxy is None:
        return

    scene.af_selection_sync_lock = True
    try:
        for o in context.selected_objects:
            o.select_set(False)
        proxy.select_set(True)
        context.view_layer.objects.active = proxy
    finally:
        scene.af_selection_sync_lock = False


class AF_SCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="")
    shape_type: bpy.props.StringProperty(name="Shape Type")

    local_origin: bpy.props.FloatVectorProperty(
        name="Translate", size=3, subtype="TRANSLATION", update=_on_scp_prop_update
    )

    local_rotation: bpy.props.FloatVectorProperty(
        name="Rotation (Quat)", size=4, subtype="QUATERNION", update=_on_quat_update
    )

    local_rotation_euler: bpy.props.FloatVectorProperty(
        name="Rotate", size=3, subtype="EULER", update=_on_euler_update
    )

    local_scale: bpy.props.FloatVectorProperty(
        name="Scale", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), update=_on_scp_prop_update
    )

    ellipsoid_radii: bpy.props.FloatVectorProperty(
        name="Radii", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), min=0.001, update=_on_scp_prop_update
    )
    ellipsoid_resolution: bpy.props.IntProperty(
        name="Resolution", default=8, min=3, max=128, update=_on_scp_prop_update
    )

    curve_length: bpy.props.FloatProperty(
        name="Length", default=1.0, min=0.001, update=_on_scp_prop_update
    )
    curve_segments: bpy.props.IntProperty(
        name="Segments", default=5, min=1, max=256, update=_on_scp_prop_update
    )

    mesh_asset_id: bpy.props.StringProperty(
        name="Mesh Asset ID", default="", update=_on_scp_prop_update
    )

    parent_id: bpy.props.StringProperty(name="Parent ID")
    attach_param: bpy.props.StringProperty(name="Attach Param JSON")

    mirror_enabled: bpy.props.BoolProperty(
        name="Mirror Enabled", default=False, update=_on_scp_prop_update
    )
    mirror_axis: bpy.props.EnumProperty(
        name="Mirror Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
        update=_on_scp_prop_update,
    )
    mirror_origin: bpy.props.FloatVectorProperty(
        name="Mirror Origin", size=3, subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0), update=_on_scp_prop_update
    )


class AF_SCP_System_Property(bpy.types.PropertyGroup):
    scps: bpy.props.CollectionProperty(type=AF_SCP_Property)
    active_scp_index: bpy.props.IntProperty(update=_on_active_scp_index_update)
