import bpy

from ..app.runtime_api import dispatch_intent_context, sync_context
from ..core.deps.dirty_hints import dirty_hints_for, empty_dirty_hints
from ..core.scp_runtime.prop_update_guard import scp_prop_updates_suppressed


def _sync_scene(context, scp_id=None, source="property", event_type="UPDATE"):
    hints = dirty_hints_for("SCP", {scp_id}) if scp_id else empty_dirty_hints()
    sync_context(context, dirty_hints=hints, source=source, event_type=event_type)


def _on_scp_prop_update(self, context):
    if scp_prop_updates_suppressed():
        return
    _sync_scene(context, getattr(self, "id", ""))


def _on_attachment_capture_update(self, context):
    if not getattr(self, "parent_id", ""):
        return
    _dispatch_attachment_recapture(context, getattr(self, "id", ""))


def _on_attach_strategy_update(self, context):
    _on_attachment_capture_update(self, context)


def _dispatch_attachment_recapture(context, scp_id):
    if not scp_id:
        return
    dispatch_intent_context(
        context,
        intent_type="SCP/RECAPTURE_ATTACHMENT",
        entity_type="SCP",
        entity_id=str(scp_id or ""),
        source="property",
        event_type="UPDATE",
    )


def _mirror_shift_index(self):
    axis = str(getattr(self, "mirror_axis", "X") or "X").upper()
    return {"Y": 1, "Z": 2}.get(axis, 0)


def _get_mirror_shift(self):
    origin = tuple(getattr(self, "mirror_origin", (0.0, 0.0, 0.0)))
    return float(origin[_mirror_shift_index(self)])


def _set_mirror_shift(self, value):
    origin = list(getattr(self, "mirror_origin", (0.0, 0.0, 0.0)))[:3]
    origin += [0.0] * (3 - len(origin))
    origin[_mirror_shift_index(self)] = float(value)
    self.mirror_origin = tuple(origin)


class AF_SCP_BoundObject_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    label: bpy.props.StringProperty(name="Label", default="")
    object_ref: bpy.props.PointerProperty(name="Object", type=bpy.types.Object)
    native_parenting_enabled: bpy.props.BoolProperty(
        name="Native Parenting",
        description="When enabled, this object is parented to the SCP transform object in Blender parenting",
        default=True,
    )


class AF_SCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="", update=_on_scp_prop_update)
    transform_object_ref: bpy.props.PointerProperty(name="Transform Object", type=bpy.types.Object)
    geometry_object_ref: bpy.props.PointerProperty(name="Geometry Object", type=bpy.types.Object)
    bound_objects: bpy.props.CollectionProperty(type=AF_SCP_BoundObject_Property)
    color: bpy.props.FloatVectorProperty(
        name="Color",
        size=4,
        subtype="COLOR",
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
        update=_on_scp_prop_update,
    )
    color_initialized: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    parent_id: bpy.props.StringProperty(name="Parent ID", default="", update=_on_scp_prop_update)
    attach_parent_anchor_mode: bpy.props.EnumProperty(
        name="Parent Anchor",
        items=[
            ("SURFACE_NEAREST", "Surface Nearest", "Anchor against the nearest point on the parent surface"),
            ("OBJECT_ORIGIN", "Object Origin", "Anchor against the parent object origin"),
        ],
        default="SURFACE_NEAREST",
        update=_on_attachment_capture_update,
    )
    attach_child_anchor_mode: bpy.props.EnumProperty(
        name="Child Anchor",
        items=[
            ("FACE_CENTER", "Face Center", "Use the nearest child face center"),
            ("VERTEX_NEAREST", "Nearest Vertex", "Use the nearest child mesh vertex"),
            ("OBJECT_ORIGIN", "Object Origin", "Use the child object origin"),
        ],
        default="FACE_CENTER",
        update=_on_attachment_capture_update,
    )
    attach_child_face_lock_index: bpy.props.IntProperty(default=-1, options={"HIDDEN"})
    attach_child_vertex_lock_index: bpy.props.IntProperty(default=-1, options={"HIDDEN"})
    attach_follow_rotation: bpy.props.BoolProperty(name="Follow Parent Rotation", default=True, update=_on_scp_prop_update)
    attach_tangent_strategy: bpy.props.EnumProperty(
        name="Rotation Strategy",
        items=[
            ("AUTO", "Auto", "Use deformation flow when the parent exposes a flow direction"),
            ("STABLE_SURFACE", "Stable Surface", "Keep rotation stable against triangle drift"),
            ("DEFORMATION_FLOW", "Deformation Flow", "Follow the stored parent surface flow"),
        ],
        default="AUTO",
        update=_on_attach_strategy_update,
    )
    mirror_enabled: bpy.props.BoolProperty(name="Mirror Children", default=False, update=_on_scp_prop_update)
    mirror_inherit_parent: bpy.props.BoolProperty(name="Inherit Parent Mirror", default=True, update=_on_scp_prop_update)
    mirror_axis: bpy.props.EnumProperty(
        name="Mirror Axis",
        items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")],
        default="X",
        update=_on_scp_prop_update,
    )
    mirror_shift: bpy.props.FloatProperty(name="Mirror Shift", get=_get_mirror_shift, set=_set_mirror_shift)
    mirror_origin: bpy.props.FloatVectorProperty(name="Mirror Origin", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0), update=_on_scp_prop_update)


class AF_SCP_System_Property(bpy.types.PropertyGroup):
    scps: bpy.props.CollectionProperty(type=AF_SCP_Property)
    active_scp_index: bpy.props.IntProperty(default=-1)
