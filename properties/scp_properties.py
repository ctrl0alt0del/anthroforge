import bpy

from ..core.deps.dirty_hints import dirty_hints_for, empty_dirty_hints
from ..core.deps.runtime_intents import dispatch_runtime_intent
from ..core.utils import get_af_root


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


def _on_child_anchor_mode_update(self, context):
    if not getattr(self, "parent_id", ""):
        return
    _dispatch_attachment_recapture(context, getattr(self, "id", ""))


def _dispatch_attachment_recapture(context, scp_id):
    if not scp_id:
        return
    dispatch_runtime_intent(
        scene=context.scene if context else None,
        intent_type="SCP/RECAPTURE_ATTACHMENT",
        entity_type="SCP",
        entity_id=str(scp_id or ""),
        source="property",
        event_type="UPDATE",
    )


class AF_SCP_BoundObject_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    label: bpy.props.StringProperty(name="Label", default="")
    object_ref: bpy.props.PointerProperty(name="Object", type=bpy.types.Object)


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
    attach_child_anchor_mode: bpy.props.EnumProperty(
        name="Child Anchor",
        items=[
            ("FACE_CENTER", "Face Center", "Use the nearest child face center"),
            ("VERTEX_NEAREST", "Nearest Vertex", "Use the nearest child mesh vertex"),
            ("OBJECT_ORIGIN", "Object Origin", "Use the child object origin"),
        ],
        default="FACE_CENTER",
        update=_on_child_anchor_mode_update,
    )

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
    active_scp_index: bpy.props.IntProperty(default=-1)
