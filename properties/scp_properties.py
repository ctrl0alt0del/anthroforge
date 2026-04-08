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


def _on_constraint_prop_update(self, context):
    # Re-capture baseline after any constraint setting changes so
    # edits do not cause immediate jumps.
    try:
        self.delta_initialized = False
        self.runtime_status = "OK"
        self.runtime_message = ""
    except Exception:
        pass
    # Constraint sub-properties do not have direct owner id; keep it simple/safe.
    _sync_scene(context, None)


def _poll_constraint_source_scp_proxy(self, obj):
    return bool(
        obj
        and obj.get("af_proxy")
        and not obj.get("af_mirror_proxy")
        and obj.get("af_scp_id")
    )


def _on_constraint_source_obj_update(self, context):
    src_obj = getattr(self, "source_obj", None)
    if src_obj and src_obj.get("af_scp_id"):
        self.source_scp_id = str(src_obj.get("af_scp_id"))
    _on_constraint_prop_update(self, context)


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


def _reset_parallelepiped_points_box(scp_prop, size):
    sx = float(size[0]) * 0.5
    sy = float(size[1]) * 0.5
    sz = float(size[2]) * 0.5

    pts = [
        (-sx, -sy, -sz),
        ( sx, -sy, -sz),
        ( sx,  sy, -sz),
        (-sx,  sy, -sz),
        (-sx, -sy,  sz),
        ( sx, -sy,  sz),
        ( sx,  sy,  sz),
        (-sx,  sy,  sz),
    ]

    while len(scp_prop.parallelepiped_points) > 0:
        scp_prop.parallelepiped_points.remove(len(scp_prop.parallelepiped_points) - 1)
    for co in pts:
        p = scp_prop.parallelepiped_points.add()
        p.co = co


def _on_parallelepiped_size_update(self, context):
    _reset_parallelepiped_points_box(self, self.parallelepiped_size)
    _sync_scene(context, getattr(self, "id", ""))


class AF_ParallelepipedPoint_Property(bpy.types.PropertyGroup):
    co: bpy.props.FloatVectorProperty(
        name="Vertex",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
        update=_on_scp_prop_update,
    )


class AF_SCP_Constraint_Property(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(name="Enabled", default=True, update=_on_constraint_prop_update)
    priority: bpy.props.IntProperty(name="Priority", default=100, min=0, max=10000, update=_on_constraint_prop_update)

    source_scp_id: bpy.props.StringProperty(name="Source SCP ID", default="", update=_on_constraint_prop_update)
    source_obj: bpy.props.PointerProperty(
        name="Source SCP",
        type=bpy.types.Object,
        poll=_poll_constraint_source_scp_proxy,
        update=_on_constraint_source_obj_update,
    )

    source_prop: bpy.props.EnumProperty(
        name="Source",
        items=[
            ("PAR_SIZE_X", "Parallelepiped Size X", ""),
            ("PAR_SIZE_Y", "Parallelepiped Size Y", ""),
            ("PAR_SIZE_Z", "Parallelepiped Size Z", ""),
            ("PAR_BEND_RADIUS", "Parallelepiped Bend Radius", ""),
            ("PAR_BEND_ANGLE", "Parallelepiped Bend Angle", ""),
            ("PAR_RESOLUTION", "Parallelepiped Resolution", ""),
            ("ELL_RAD_X", "Ellipsoid Radius X", ""),
            ("ELL_RAD_Y", "Ellipsoid Radius Y", ""),
            ("ELL_RAD_Z", "Ellipsoid Radius Z", ""),
            ("CURVE_LENGTH", "Curve Length", ""),
            ("LOCAL_SCALE_X", "Local Scale X", ""),
            ("LOCAL_SCALE_Y", "Local Scale Y", ""),
            ("LOCAL_SCALE_Z", "Local Scale Z", ""),
        ],
        default="PAR_SIZE_X",
        update=_on_constraint_prop_update,
    )

    dest_prop: bpy.props.EnumProperty(
        name="Destination",
        items=[
            ("PAR_BEND_RADIUS", "Parallelepiped Bend Radius", ""),
            ("PAR_BEND_ANGLE", "Parallelepiped Bend Angle", ""),
            ("PAR_RESOLUTION", "Parallelepiped Resolution", ""),
            ("LOCAL_SCALE_X", "Local Scale X", ""),
            ("LOCAL_SCALE_Y", "Local Scale Y", ""),
            ("LOCAL_SCALE_Z", "Local Scale Z", ""),
        ],
        default="PAR_BEND_RADIUS",
        update=_on_constraint_prop_update,
    )

    calculator_type: bpy.props.EnumProperty(
        name="Calculator",
        items=[
            ("LINEAR", "Linear", ""),
            ("RANGE_REMAP", "Range Remap", ""),
            ("ARC_BRIDGE", "Arc Bridge", ""),
        ],
        default="LINEAR",
        update=_on_constraint_prop_update,
    )

    # LINEAR: y = a*x + b
    linear_a: bpy.props.FloatProperty(name="a", default=1.0, update=_on_constraint_prop_update)
    linear_b: bpy.props.FloatProperty(name="b", default=0.0, update=_on_constraint_prop_update)

    # RANGE_REMAP
    in_min: bpy.props.FloatProperty(name="In Min", default=0.0, update=_on_constraint_prop_update)
    in_max: bpy.props.FloatProperty(name="In Max", default=1.0, update=_on_constraint_prop_update)
    out_min: bpy.props.FloatProperty(name="Out Min", default=0.0, update=_on_constraint_prop_update)
    out_max: bpy.props.FloatProperty(name="Out Max", default=1.0, update=_on_constraint_prop_update)
    clamp: bpy.props.BoolProperty(name="Clamp", default=True, update=_on_constraint_prop_update)

    # ARC_BRIDGE
    arc_source_width_prop: bpy.props.EnumProperty(
        name="Source Width",
        items=[
            ("PAR_SIZE_X", "Parallelepiped Size X", ""),
            ("PAR_SIZE_Y", "Parallelepiped Size Y", ""),
            ("PAR_SIZE_Z", "Parallelepiped Size Z", ""),
            ("ELL_RAD_X", "Ellipsoid Radius X", ""),
            ("ELL_RAD_Y", "Ellipsoid Radius Y", ""),
            ("ELL_RAD_Z", "Ellipsoid Radius Z", ""),
            ("CURVE_LENGTH", "Curve Length", ""),
            ("LOCAL_SCALE_X", "Local Scale X", ""),
            ("LOCAL_SCALE_Y", "Local Scale Y", ""),
            ("LOCAL_SCALE_Z", "Local Scale Z", ""),
        ],
        default="PAR_SIZE_X",
        update=_on_constraint_prop_update,
    )
    arc_dest_angle_prop: bpy.props.EnumProperty(
        name="Destination Angle",
        items=[
            ("PAR_BEND_ANGLE", "Parallelepiped Bend Angle", ""),
        ],
        default="PAR_BEND_ANGLE",
        update=_on_constraint_prop_update,
    )
    arc_full_angle: bpy.props.FloatProperty(
        name="Full Angle",
        default=360.0,
        min=1.0,
        max=720.0,
        update=_on_constraint_prop_update,
    )
    arc_width_scale: bpy.props.FloatProperty(
        name="Width Scale",
        default=1.0,
        update=_on_constraint_prop_update,
    )
    arc_width_offset: bpy.props.FloatProperty(
        name="Width Offset",
        default=0.0,
        update=_on_constraint_prop_update,
    )

    # Hidden runtime baseline for delta-mode constraint application:
    # dest = dest_base + (f(src_now) - f(src_base))
    delta_initialized: bpy.props.BoolProperty(
        default=False,
        options={"HIDDEN"},
    )
    delta_src_base: bpy.props.FloatProperty(
        default=0.0,
        options={"HIDDEN"},
    )
    delta_dst_base: bpy.props.FloatProperty(
        default=0.0,
        options={"HIDDEN"},
    )
    delta_dst_base_2: bpy.props.FloatProperty(
        default=0.0,
        options={"HIDDEN"},
    )
    runtime_status: bpy.props.EnumProperty(
        name="Status",
        items=[
            ("OK", "OK", ""),
            ("DELAYED_CYCLE", "Delayed Cycle", ""),
        ],
        default="OK",
        options={"HIDDEN"},
    )
    runtime_message: bpy.props.StringProperty(
        name="Runtime Message",
        default="",
        options={"HIDDEN"},
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
    proxy = _find_scene_scp_proxy(scene, root.name, scp_id)
    if proxy is None:
        return
    _select_only_proxy(scene, context, proxy)


def _find_scene_scp_proxy(scene, root_name, scp_id):
    for obj in scene.objects:
        if obj.get("af_proxy") and not obj.get("af_mirror_proxy") and obj.get("af_root_name") == root_name:
            if obj.get("af_scp_id") == scp_id:
                return obj
    return None


def _select_only_proxy(scene, context, proxy):
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
    ellipsoid_clip_enabled: bpy.props.BoolProperty(
        name="Enable Clipping", default=False, update=_on_scp_prop_update
    )
    ellipsoid_clip1_enabled: bpy.props.BoolProperty(
        name="Clip Plane 1", default=False, update=_on_scp_prop_update
    )
    ellipsoid_clip1_normal: bpy.props.FloatVectorProperty(
        name="Plane 1 Normal", size=3, subtype="XYZ", default=(1.0, 0.0, 0.0), update=_on_scp_prop_update
    )
    ellipsoid_clip1_offset: bpy.props.FloatProperty(
        name="Plane 1 Offset", default=0.0, update=_on_scp_prop_update
    )
    ellipsoid_clip1_keep_side: bpy.props.EnumProperty(
        name="Plane 1 Keep",
        items=[("POS", "Positive Side", ""), ("NEG", "Negative Side", "")],
        default="POS",
        update=_on_scp_prop_update,
    )
    ellipsoid_clip2_enabled: bpy.props.BoolProperty(
        name="Clip Plane 2", default=False, update=_on_scp_prop_update
    )
    ellipsoid_clip2_normal: bpy.props.FloatVectorProperty(
        name="Plane 2 Normal", size=3, subtype="XYZ", default=(-1.0, 0.0, 0.0), update=_on_scp_prop_update
    )
    ellipsoid_clip2_offset: bpy.props.FloatProperty(
        name="Plane 2 Offset", default=0.0, update=_on_scp_prop_update
    )
    ellipsoid_clip2_keep_side: bpy.props.EnumProperty(
        name="Plane 2 Keep",
        items=[("POS", "Positive Side", ""), ("NEG", "Negative Side", "")],
        default="POS",
        update=_on_scp_prop_update,
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

    parallelepiped_size: bpy.props.FloatVectorProperty(
        name="Size",
        size=3,
        subtype="XYZ",
        default=(1.0, 1.0, 1.0),
        min=0.001,
        update=_on_parallelepiped_size_update,
    )
    parallelepiped_points: bpy.props.CollectionProperty(type=AF_ParallelepipedPoint_Property)
    parallelepiped_bend_enabled: bpy.props.BoolProperty(
        name="Enable Bend",
        default=False,
        update=_on_scp_prop_update,
    )
    parallelepiped_bend_axis: bpy.props.EnumProperty(
        name="Bend Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
        update=_on_scp_prop_update,
    )
    parallelepiped_bend_angle_deg: bpy.props.FloatProperty(
        name="Bend Angle",
        default=0.0,
        min=-360.0,
        max=360.0,
        update=_on_scp_prop_update,
    )
    parallelepiped_bend_radius: bpy.props.FloatProperty(
        name="Bend Radius",
        default=1.0,
        min=0.001,
        update=_on_scp_prop_update,
    )
    parallelepiped_resolution: bpy.props.IntProperty(
        name="Resolution",
        default=4,
        min=1,
        max=64,
        update=_on_scp_prop_update,
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

    constraints: bpy.props.CollectionProperty(type=AF_SCP_Constraint_Property)
    active_constraint_index: bpy.props.IntProperty(default=0)


class AF_SCP_System_Property(bpy.types.PropertyGroup):
    scps: bpy.props.CollectionProperty(type=AF_SCP_Property)
    active_scp_index: bpy.props.IntProperty(update=_on_active_scp_index_update)
