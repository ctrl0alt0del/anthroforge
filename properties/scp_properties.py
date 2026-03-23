import bpy
from mathutils import Euler, Quaternion
from ..core.utils import get_af_root


def _sync_scene(context, scp_id=None):
    scene = context.scene if context else None
    root = get_af_root(scene)
    if root is None:
        return

    if scp_id:
        from ..core.visualization.sync_runner import sync_from_scp_ids
        sync_from_scp_ids(root=root, scene=scene, scp_ids={scp_id})
    else:
        from ..core.visualization.sync_runner import sync_all
        sync_all(root=root, scene=scene)


def _on_scp_prop_update(self, context):
    _sync_scene(context, getattr(self, "id", ""))


def _on_euler_update(self, context):
    e = Euler(self.local_rotation_euler, "XYZ")
    q = e.to_quaternion()
    self.local_rotation = (q.w, q.x, q.y, q.z)
    _sync_scene(context, getattr(self, "id", ""))


def _on_quat_update(self, context):
    q = Quaternion(self.local_rotation)
    e = q.to_euler("XYZ")
    self["local_rotation_euler"] = (e.x, e.y, e.z)
    _sync_scene(context, getattr(self, "id", ""))


def _curve_points_as_list(scp_prop):
    return [(p.co[0], p.co[1], p.co[2]) for p in scp_prop.curve_points]


def _sample_polyline(points, t):
    if not points:
        return (0.0, 0.0, 0.0)
    if len(points) == 1:
        return points[0]

    t = max(0.0, min(1.0, float(t)))
    u = t * (len(points) - 1)
    i = int(u)
    if i >= len(points) - 1:
        return points[-1]
    a = u - i

    p0 = points[i]
    p1 = points[i + 1]
    return (
        p0[0] + (p1[0] - p0[0]) * a,
        p0[1] + (p1[1] - p0[1]) * a,
        p0[2] + (p1[2] - p0[2]) * a,
    )


def _reset_curve_points_linear(scp_prop, length, segments):
    while len(scp_prop.curve_points) > 0:
        scp_prop.curve_points.remove(len(scp_prop.curve_points) - 1)

    segments = max(1, int(segments))
    length = float(length)
    for i in range(segments + 1):
        p = scp_prop.curve_points.add()
        t = i / float(segments)
        p.co = (t * length, 0.0, 0.0)


def _on_curve_length_update(self, context):
    old_len = float(self.get("_af_prev_curve_length", self.curve_length if self.curve_length > 0.0 else 1.0))
    new_len = float(self.curve_length)

    if len(self.curve_points) != self.curve_segments + 1:
        _reset_curve_points_linear(self, new_len, self.curve_segments)
    elif old_len > 1e-8 and abs(new_len - old_len) > 1e-8:
        scale = new_len / old_len
        for p in self.curve_points:
            p.co = (p.co[0] * scale, p.co[1], p.co[2])

    self["_af_prev_curve_length"] = new_len
    _sync_scene(context, getattr(self, "id", ""))


def _on_curve_segments_update(self, context):
    new_segments = max(1, int(self.curve_segments))
    old_points = _curve_points_as_list(self)

    if not old_points or len(old_points) < 2:
        _reset_curve_points_linear(self, self.curve_length, new_segments)
    else:
        while len(self.curve_points) > 0:
            self.curve_points.remove(len(self.curve_points) - 1)
        for i in range(new_segments + 1):
            p = self.curve_points.add()
            t = i / float(new_segments)
            p.co = _sample_polyline(old_points, t)

    self["_af_prev_curve_segments"] = new_segments
    _sync_scene(context, getattr(self, "id", ""))


class AF_CurvePoint_Property(bpy.types.PropertyGroup):
    co: bpy.props.FloatVectorProperty(
        name="Point",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
        update=_on_scp_prop_update,
    )


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
        name="Length", default=1.0, min=0.001, update=_on_curve_length_update
    )
    curve_segments: bpy.props.IntProperty(
        name="Segments", default=5, min=1, max=256, update=_on_curve_segments_update
    )
    curve_thickness: bpy.props.FloatProperty(
        name="Thickness", default=0.02, min=0.0, update=_on_scp_prop_update
    )
    curve_points: bpy.props.CollectionProperty(type=AF_CurvePoint_Property)
    curve_proportional_enabled: bpy.props.BoolProperty(
        name="Proportional Edit", default=True, update=_on_scp_prop_update
    )
    curve_proportional_radius: bpy.props.FloatProperty(
        name="Proportional Radius", default=2.0, min=0.001, update=_on_scp_prop_update
    )
    curve_proportional_strength: bpy.props.FloatProperty(
        name="Proportional Strength", default=0.65, min=0.0, max=1.0, update=_on_scp_prop_update
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
