import bpy

from ..core.vcp.shared_point_storage import binding_getter, binding_setter, point_updated, clear_indexes

from ..app.runtime_api import schedule_context, sync_context
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.vcp.prop_update_guard import suppress_vcp_prop_updates, vcp_prop_updates_suppressed
from ..core.vcp.soft_tissue_model import construction_mode_for_domain


def _sync_vcp_scene(self, context):
    if vcp_prop_updates_suppressed():
        return
    owner = _nested_fiber_owner(self)
    if owner is not None:
        _queue_fiber_update(owner, context, "RELATIONSHIP")


def _nested_fiber_owner(item):
    root, pointer = getattr(item, "id_data", None), _prop_pointer(item)
    fibers = getattr(getattr(root, "af_vcp_system", None), "fibers", ())
    for fiber in fibers:
        children = tuple(fiber.mid_touches) + tuple(fiber.loop_anchors)
        if any(_prop_pointer(child) == pointer for child in children):
            return fiber
    return None


def _prop_pointer(item):
    try:
        return int(item.as_pointer())
    except Exception:
        return id(item)


def _on_muscle_prop_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    sync_context(context, dirty_hints=dirty_hints_for("MUSCLE", {self.id}))


def _on_inflation_ctrl_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    self.inflation_ctrl_initialized = True
    _on_muscle_prop_update(self, context)


def _on_fiber_surface_prop_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    sync_context(context, dirty_hints=dirty_hints_for("FIBER_SURFACE", {self.id}))


def _branch_update(self, context):
    if not vcp_prop_updates_suppressed():
        _on_muscle_prop_update(self.settings, context)


def _on_blob_prop_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    sync_context(context, dirty_hints=dirty_hints_for("BLOB", {self.id}))


def _on_soft_tissue_prop_update(self, context):
    _queue_soft_tissue_update(self, context, "NONE")


def _on_soft_binding_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    _normalize_soft_domain(self)
    _queue_soft_tissue_update(self, context, "ALL")


def _on_soft_inflation_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    _normalize_soft_domain(self)
    _queue_soft_tissue_update(self, context, "NONE")


def _on_soft_rest_topology_update(self, context):
    _queue_soft_tissue_update(self, context, "REGIONS")


def _normalize_soft_domain(tissue):
    source = getattr(tissue, "base_object_ref", None)
    domain = {"EMPTY": "POINT", "CURVE": "CURVE", "MESH": "SURFACE"}.get(getattr(source, "type", ""))
    domain = domain or str(getattr(tissue, "base_domain", "SURFACE"))
    expected = construction_mode_for_domain(domain).value
    with suppress_vcp_prop_updates():
        tissue.base_domain, tissue.inflation_mode = domain, expected
        if domain == "POINT":
            tissue.boundary_mode = "CLOSED"


def _queue_soft_tissue_update(self, context, recapture_scope):
    if vcp_prop_updates_suppressed() or not str(getattr(self, "id", "") or ""):
        return
    _mark_soft_tissue_dirty(self)
    hints = dirty_hints_for("SOFT_TISSUE", {self.id})
    payload = _soft_recapture_payload(self.id, recapture_scope)
    schedule_context(context, dirty_hints=hints, event_type="SOFT_TISSUE_UPDATE", payload=payload)


def _soft_recapture_payload(tissue_id, scope):
    keys = {"ALL": "soft_tissue_recapture_ids", "BASE": "soft_tissue_base_recapture_ids",
            "REGIONS": "soft_tissue_region_recapture_ids"}
    key = keys.get(str(scope or "NONE"))
    return {} if key is None else {key: [str(tissue_id)]}


def _on_soft_attachment_update(self, context):
    owner = _soft_attachment_owner(getattr(self, "id_data", None), self)
    if owner is not None:
        _on_soft_tissue_prop_update(owner, context)


def _on_soft_attachment_binding_update(self, context):
    owner = _soft_attachment_owner(getattr(self, "id_data", None), self)
    if owner is not None:
        _queue_soft_tissue_update(owner, context, "REGIONS")


def _on_soft_rest_update(self, context):
    scene = None if context is None else getattr(context, "scene", None)
    if scene is None:
        return
    for obj in scene.objects:
        if obj.get("af_soft_tissue_rest_proxy") and obj.get("af_soft_tissue_id") == self.id:
            obj.hide_viewport = not bool(self.show_rest)


def _soft_attachment_owner(root, attachment):
    vcp = None if root is None else getattr(root, "af_vcp_system", None)
    for tissue in (() if vcp is None else vcp.soft_tissues):
        if any(item.as_pointer() == attachment.as_pointer() for item in tissue.attachments):
            return tissue
    return None


def _mark_soft_tissue_dirty(tissue):
    try:
        from ..core.vcp.runtime_state import set_soft_tissue_status
        set_soft_tissue_status(tissue, "DIRTY")
    except Exception:
        return


def _on_fiber_prop_update(self, context):
    _queue_fiber_update(self, context, "SOLVER")


def _on_fiber_topology_update(self, context):
    _queue_fiber_update(self, context, "RELATIONSHIP")


def _on_fiber_attachment_update(self, context):
    _queue_fiber_update(self, context, "ATTACHMENT")


def _queue_fiber_update(self, context, aspect):
    fiber_id = str(getattr(self, "id", "") or "")
    if vcp_prop_updates_suppressed() or not fiber_id:
        return
    _invalidate_fiber_preflight(self, context)
    aspects = {"FIBER": {str(aspect)}}
    schedule_context(context, dirty_hints=dirty_hints_for("FIBER", {fiber_id}),
                     event_type="FIBER_UPDATE", dirty_aspects=aspects)


def _invalidate_fiber_preflight(fiber, context):
    from ..core.vcp.fiber_anchor_preflight import (clear_transient_fiber_attachment_statuses,
                                                    invalidate_fiber_anchor_preflight)
    root = getattr(fiber, "id_data", None)
    scene = None if context is None else getattr(context, "scene", None)
    ids = {str(getattr(fiber, "id", "") or "")}
    invalidate_fiber_anchor_preflight(scene, root, ids)
    clear_transient_fiber_attachment_statuses(root, ids)


def _on_fiber_display_update(self, context):
    if vcp_prop_updates_suppressed():
        return
    root = getattr(self, "id_data", None)
    scene = None if context is None else getattr(context, "scene", None)
    if root is not None and scene is not None:
        _fiber_scene_sync().refresh_display(root, scene, {self.id})


def _fiber_scene_sync():
    from ..core.visualization.fiber_sync import register_fiber_sync
    return register_fiber_sync()


class AF_MuscleFiberRef_Property(bpy.types.PropertyGroup):
    fiber_id: bpy.props.StringProperty(name="Fiber ID", default="")


class AF_FiberSurfaceFiberRef_Property(bpy.types.PropertyGroup):
    fiber_id: bpy.props.StringProperty(name="Fiber ID", default="")


class AF_MuscleVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Muscle", update=_on_muscle_prop_update)
    surface_source_mode: bpy.props.EnumProperty(
        name="Surface Source", items=(("LEGACY_FIBERS", "Legacy Fibers", ""),
        ("FIBER_SURFACE", "Fiber Surface", "")), default="LEGACY_FIBERS", update=_on_muscle_prop_update,
    )
    fiber_surface_id: bpy.props.StringProperty(name="Fiber Surface ID", default="", update=_on_muscle_prop_update)

    closed_v: bpy.props.BoolProperty(name="Closed Ring (V)", default=False, update=_on_muscle_prop_update)
    use_mirrored_rows: bpy.props.BoolProperty(name="Use Mirrored Rows", default=False, update=_on_muscle_prop_update)

    fiber_refs: bpy.props.CollectionProperty(type=AF_MuscleFiberRef_Property)
    active_fiber_ref_index: bpy.props.IntProperty(name="Active Fiber Ref", default=-1)

    inflation_enabled: bpy.props.BoolProperty(name="Inflation Enabled", default=True, update=_on_muscle_prop_update)
    inflation_ctrl_world: bpy.props.FloatVectorProperty(
        name="Inflation Control Position", size=3, default=(0.0, 0.0, 0.0),
        options={"HIDDEN"}, update=_on_inflation_ctrl_update,
    )
    inflation_ctrl_initialized: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    inflation_mode: bpy.props.EnumProperty(
        name="Inflation Mode",
        items=(
            ("CTRL_POINT", "Control Point", ""),
            ("DISTRIBUTED", "Distributed", ""),
        ),
        default="CTRL_POINT",
        update=_on_muscle_prop_update,
    )
    inflation_max_value: bpy.props.FloatProperty(
        name="Max Inflation",
        default=0.05,
        min=0.0,
        max=10.0,
        update=_on_muscle_prop_update,
    )
    inflation_falloff_type: bpy.props.EnumProperty(
        name="Falloff",
        items=(
            ("GAUSSIAN", "Gaussian", ""),
            ("LINEAR", "Linear", ""),
            ("SMOOTHSTEP", "Smoothstep", ""),
        ),
        default="GAUSSIAN",
        update=_on_muscle_prop_update,
    )
    inflation_falloff_radius: bpy.props.FloatProperty(
        name="Falloff Radius",
        default=0.2,
        min=0.001,
        max=100.0,
        update=_on_muscle_prop_update,
    )

    inflation_direction_depth: bpy.props.FloatProperty(
        name="Direction Depth (L)",
        default=0.05,
        min=0.0001,
        max=10.0,
        update=_on_muscle_prop_update,
    )

    inflation_boundary_strength: bpy.props.FloatProperty(
        name="Boundary Strength",
        default=0.7, min=0.0, max=1.0, update=_on_muscle_prop_update
    )

    inflation_boundary_band: bpy.props.FloatProperty(
        name="Boundary Band",
        default=2.0, min=0.1, max=16.0, update=_on_muscle_prop_update
    )

    inflation_boundary_power: bpy.props.FloatProperty(
        name="Boundary Power",
        default=1.5, min=0.1, max=8.0, update=_on_muscle_prop_update
    )

    inflation_length_taper_band: bpy.props.FloatProperty(
        name="Length Taper Band",
        default=0.2,
        min=0.01,
        max=0.49,
        update=_on_muscle_prop_update,
    )

    flip_normals: bpy.props.BoolProperty(
        name="Flip Normals",
        default=False,
        update=_on_muscle_prop_update,
    )


class AF_BranchPointRef_Property(bpy.types.PropertyGroup):
    point_id: bpy.props.StringProperty(name="Shared Root Point")


class AF_BranchConnection_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="Connection ID")
    surface_id: bpy.props.StringProperty(name="Branch Surface")
    boundary_fiber_id: bpy.props.StringProperty(name="Main Boundary Fiber")
    roots: bpy.props.CollectionProperty(type=AF_BranchPointRef_Property)
    settings: bpy.props.PointerProperty(type=AF_MuscleVCP_Property)
    width: bpy.props.FloatProperty(name="Connector Width", default=.25, min=.01, max=.49, update=_branch_update)
    fullness: bpy.props.FloatProperty(name="Connector Fullness", default=0., update=_branch_update)


class AF_FiberSurfaceVCP_Property(bpy.types.PropertyGroup):
    main_surface_id: bpy.props.StringProperty(name="Main Surface")
    branches: bpy.props.CollectionProperty(type=AF_BranchConnection_Property)
    active_branch_index: bpy.props.IntProperty(default=-1)
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Fiber Surface", update=_on_fiber_surface_prop_update)
    schema_version: bpy.props.IntProperty(name="Schema", default=1, min=1)
    construction_mode: bpy.props.EnumProperty(
        name="Construction", items=(("LOFT", "Loft", ""), ("LOOP_PATCH", "Loop Patch", ""), ("BRANCHED_LOFT", "Branched Loft", "")),
        default="LOFT", update=_on_fiber_surface_prop_update,
    )
    fiber_refs: bpy.props.CollectionProperty(type=AF_FiberSurfaceFiberRef_Property)
    active_fiber_ref_index: bpy.props.IntProperty(name="Active Fiber Ref", default=-1)
    close_across_fibers: bpy.props.BoolProperty(name="Close Across Fibers", default=False, update=_on_fiber_surface_prop_update)
    use_mirrored_rows: bpy.props.BoolProperty(name="Use Mirrored Rows", default=False, update=_on_fiber_surface_prop_update)
    flip_normals: bpy.props.BoolProperty(name="Flip Normals", default=False, update=_on_fiber_surface_prop_update)
    patch_resolution: bpy.props.IntProperty(name="Patch Resolution", default=4, min=1, max=64, update=_on_fiber_surface_prop_update)


class AF_AuthoredPoint_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="Point ID", update=clear_indexes)
    parent_id: bpy.props.StringProperty(name="SCP ID", update=point_updated)
    attach_param: bpy.props.StringProperty(name="Indexed binding", default="0.0", update=point_updated)
    normal_offset: bpy.props.FloatProperty(name="Normal Offset", update=point_updated)


def _binding_string(slot, field, legacy, label, default=""):
    return bpy.props.StringProperty(name=label, get=binding_getter(slot, field, legacy, default),
                                    set=binding_setter(slot, field))


class AF_FiberTouchPoint_Property(bpy.types.PropertyGroup):
    point_id: bpy.props.StringProperty(name="Shared Point ID")
    parent_id: _binding_string("point_id", "parent_id", "parent_id", "Touch SCP ID")
    attach_param: _binding_string("point_id", "attach_param", "attach_param", "Touch Attach Param JSON", "0.0")
    normal_offset: bpy.props.FloatProperty(name="Normal Offset",
        get=binding_getter("point_id", "normal_offset", "normal_offset", 0.0),
        set=binding_setter("point_id", "normal_offset"))


class AF_FiberLoopAnchor_Property(bpy.types.PropertyGroup):
    point_id: bpy.props.StringProperty(name="Shared Point ID")
    parent_id: _binding_string("point_id", "parent_id", "parent_id", "Loop SCP ID")
    attach_param: _binding_string("point_id", "attach_param", "attach_param", "Loop Attach Param JSON", "0.0")


class AF_FiberVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="")

    topology_mode: bpy.props.EnumProperty(
        name="Topology",
        items=(("OPEN", "Open", ""), ("LOOP", "Loop", "")),
        default="OPEN",
        update=_on_fiber_topology_update,
    )
    symmetry_mode: bpy.props.EnumProperty(
        name="Symmetry",
        items=(("NONE", "None", ""), ("MIRROR_SEAM_LOOP", "Mirror Seam Loop", "")),
        default="NONE",
        update=_on_fiber_topology_update,
    )
    symmetry_axis: bpy.props.EnumProperty(
        name="Symmetry Axis",
        items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")),
        default="X",
        update=_on_fiber_topology_update,
    )
    symmetry_origin: bpy.props.FloatVectorProperty(
        name="Symmetry Origin",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
        update=_on_fiber_topology_update,
    )
    a_point_id: bpy.props.StringProperty(name="Origin Point ID")
    b_point_id: bpy.props.StringProperty(name="Insertion Point ID")
    a_parent_id: _binding_string("a_point_id", "parent_id", "a_parent_id", "Origin parent_id")
    a_attach_param: _binding_string("a_point_id", "attach_param", "a_attach_param", "Origin attach_param")
    b_parent_id: _binding_string("b_point_id", "parent_id", "b_parent_id", "Insertion parent_id")
    b_attach_param: _binding_string("b_point_id", "attach_param", "b_attach_param", "Insertion attach_param")

    mid_touches: bpy.props.CollectionProperty(type=AF_FiberTouchPoint_Property)
    loop_anchors: bpy.props.CollectionProperty(type=AF_FiberLoopAnchor_Property)

    muscle_id: bpy.props.StringProperty(name="Muscle ID", default="")

    solver_version: bpy.props.IntProperty(name="Solver Version", default=1, min=1, max=3, update=_on_fiber_prop_update)
    collision_radius: bpy.props.FloatProperty(name="Collision Radius", subtype="DISTANCE", default=0.002,
                                              min=0.0, update=_on_fiber_prop_update)
    use_warm_start: bpy.props.BoolProperty(name="Use Warm Start", default=True, update=_on_fiber_prop_update)
    node_attachments_json: bpy.props.StringProperty(default="", options={"HIDDEN"})
    use_surface_routing: bpy.props.BoolProperty(name="Use Surface Routing", default=False, update=_on_fiber_prop_update)
    use_segment_collisions: bpy.props.BoolProperty(name="Segment Collisions", default=False, update=_on_fiber_prop_update)
    preview_planner_route: bpy.props.BoolProperty(name="Preview Planner Route", default=False, update=_on_fiber_prop_update)
    node_count: bpy.props.IntProperty(name="Node Count", default=64, min=8, max=512, update=_on_fiber_prop_update)
    iterations_interactive: bpy.props.IntProperty(name="Iterations (Interactive)", default=12, min=1, max=200, update=_on_fiber_prop_update)
    iterations_bake: bpy.props.IntProperty(name="Iterations (Bake)", default=120, min=1, max=1000)

    bend_stiffness: bpy.props.FloatProperty(name="Bend Stiffness", default=0.15, min=0.0, max=1.0, update=_on_fiber_prop_update)

    stretch_stiffness: bpy.props.FloatProperty(name="Shorten Strength", default=0.9, min=0.0, max=1.0, update=_on_fiber_prop_update)

    thickness: bpy.props.FloatProperty(name="Thickness", default=0.01, min=0.0, update=_on_fiber_display_update)
    legacy_points_json: bpy.props.StringProperty(default="", options={"HIDDEN"})
    legacy_diagnostics_json: bpy.props.StringProperty(default="", options={"HIDDEN"})
    legacy_status: bpy.props.StringProperty(default="", options={"HIDDEN"})
    legacy_eps_disp: bpy.props.FloatProperty(default=0.0, options={"HIDDEN"})
    legacy_eps_pen: bpy.props.FloatProperty(default=0.0, options={"HIDDEN"})


class AF_BlobVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Blob", update=_on_blob_prop_update)

    center_world: bpy.props.FloatVectorProperty(
        name="Center", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0), update=_on_blob_prop_update
    )
    radius: bpy.props.FloatProperty(name="Radius", default=0.2, min=0.001, update=_on_blob_prop_update)
    shape: bpy.props.EnumProperty(
        name="Shape",
        items=(("SPHERE", "Sphere", ""), ("ELLIPSOID", "Ellipsoid", "")),
        default="SPHERE",
        update=_on_blob_prop_update,
    )
    axis_scale: bpy.props.FloatVectorProperty(
        name="Axis Scale", size=3, subtype="XYZ", default=(1.0, 1.0, 1.0), min=0.001, update=_on_blob_prop_update
    )
    resolution: bpy.props.IntProperty(name="Control Points", default=24, min=8, max=128, update=_on_blob_prop_update)

    # Explicit point used by solver ray tests.
    control_point_world: bpy.props.FloatVectorProperty(
        name="Control Point",
        size=3,
        subtype="TRANSLATION",
        default=(0.0, 0.0, 0.0),
        update=_on_blob_prop_update,
    )

    gravity_dir: bpy.props.FloatVectorProperty(
        name="Gravity Dir", size=3, subtype="XYZ", default=(0.0, 0.0, -1.0), update=_on_blob_prop_update
    )
    sag_strength: bpy.props.FloatProperty(name="Sag Strength", default=0.35, min=0.0, max=10.0, update=_on_blob_prop_update)
    sag_limit: bpy.props.FloatProperty(name="Sag Limit", default=0.35, min=0.0, max=100.0, update=_on_blob_prop_update)

    attach_target_type: bpy.props.EnumProperty(
        name="Target Type",
        items=(("NONE", "None", ""), ("MUSCLE", "Muscle", ""), ("SCP", "SCP", ""), ("OBJECT", "Object", "")),
        default="NONE",
        update=_on_blob_prop_update,
    )
    attach_target_id: bpy.props.StringProperty(name="Target ID", default="", update=_on_blob_prop_update)
    attach_target_object_name: bpy.props.StringProperty(name="Target Object", default="", update=_on_blob_prop_update)

    stiffness: bpy.props.FloatProperty(name="Stiffness", default=0.25, min=0.0, max=1.0, update=_on_blob_prop_update)
    iterations: bpy.props.IntProperty(name="Iterations", default=20, min=1, max=200, update=_on_blob_prop_update)


class AF_SoftTissueAttachment_Property(bpy.types.PropertyGroup):
    mode: bpy.props.EnumProperty(
        name="Mode", items=(("FIXED", "Fixed", ""), ("SOFT", "Soft", "")),
        default="SOFT", update=_on_soft_attachment_update,
    )
    strength: bpy.props.FloatProperty(
        name="Strength", default=0.5, min=0.0, max=1.0, update=_on_soft_attachment_update,
    )
    feather: bpy.props.FloatProperty(
        name="Attachment Feather", description="Geodesic soft-falloff width relative to the base surface size",
        default=0.0, min=0.0, max=1.0, subtype="FACTOR", update=_on_soft_attachment_binding_update,
    )
    mask_attribute: bpy.props.StringProperty(
        name="Mask", default="ALL", update=_on_soft_attachment_binding_update,
    )
    normal_offset: bpy.props.FloatProperty(
        name="Normal Offset", default=0.0, update=_on_soft_attachment_update,
    )
    bindings_json: bpy.props.StringProperty(name="Bindings", default="[]", options={"HIDDEN"})


class AF_SoftTissueVCP_Property(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty(name="ID")
    name: bpy.props.StringProperty(name="Name", default="Soft Tissue", update=_on_soft_tissue_prop_update)
    schema_version: bpy.props.IntProperty(name="Schema", default=2, min=1, max=2)
    base_source_type: bpy.props.EnumProperty(
        name="Base Source", items=(("OBJECT", "Object", ""), ("FIBER", "Fiber", ""),
        ("FIBER_SURFACE", "Fiber Surface", "")), default="OBJECT", update=_on_soft_binding_update,
    )
    base_source_id: bpy.props.StringProperty(name="Base Source ID", default="", update=_on_soft_binding_update)
    preset: bpy.props.EnumProperty(
        name="Preset", items=(("CUSTOM", "Custom", ""), ("CLOSED_BULK", "Closed Bulk", ""),
        ("RIM", "Rim", ""), ("LAYER", "Layer", ""), ("POUCH", "Pouch", "")),
        default="CUSTOM",
    )
    base_domain: bpy.props.EnumProperty(
        name="Domain", items=(("POINT", "Point", ""), ("CURVE", "Curve", ""),
        ("SURFACE", "Surface", "")), default="SURFACE", update=_on_soft_binding_update,
    )
    base_object_ref: bpy.props.PointerProperty(
        name="Base Object", type=bpy.types.Object, update=_on_soft_binding_update,
    )
    base_owned: bpy.props.BoolProperty(name="Owned Base", default=False)
    base_resolution: bpy.props.IntProperty(
        name="Resolution", default=24, min=3, max=512, update=_on_soft_binding_update,
    )
    base_closed: bpy.props.BoolProperty(name="Closed Base", default=False)
    base_signature: bpy.props.StringProperty(name="Base Signature", default="", options={"HIDDEN"})
    host_scp_id: bpy.props.StringProperty(name="Host SCP", default="", update=_on_soft_binding_update)
    host_surface: bpy.props.EnumProperty(
        name="Host Surface", items=(("SCP_GEOMETRY", "SCP Geometry", ""),),
        default="SCP_GEOMETRY", update=_on_soft_binding_update,
    )
    host_topology_signature: bpy.props.StringProperty(name="Host Signature", default="", options={"HIDDEN"})
    attachment_target_type: bpy.props.EnumProperty(
        name="Target Type", items=(("NONE", "None", ""), ("SCP", "SCP", ""),
        ("MUSCLE", "Muscle", "")), default="NONE", update=_on_soft_binding_update,
    )
    attachment_target_id: bpy.props.StringProperty(name="Target ID", default="", update=_on_soft_binding_update)
    attachment_target_surface: bpy.props.EnumProperty(
        name="Target Surface", items=(("AUTO", "Auto", ""), ("SCP_GEOMETRY", "SCP Geometry", ""),
        ("MUSCLE_BASE", "Muscle Base", ""), ("MUSCLE_INFL", "Muscle Inflated", "")),
        default="AUTO", update=_on_soft_binding_update,
    )
    attachment_topology_signature: bpy.props.StringProperty(name="Target Signature", default="", options={"HIDDEN"})
    control_bindings_json: bpy.props.StringProperty(name="Control Bindings", default="[]", options={"HIDDEN"})
    base_bindings_json: bpy.props.StringProperty(name="Base Bindings", default="[]", options={"HIDDEN"})
    boundary_mode: bpy.props.EnumProperty(
        name="Boundary", items=(("CLOSED", "Closed", ""), ("HOST_SEALED", "Host Sealed", "")),
        default="HOST_SEALED", update=_on_soft_tissue_prop_update,
    )
    inflation_mode: bpy.props.EnumProperty(
        name="Inflation", items=(("RADIAL", "Radial", ""),
        ("NORMAL", "Normal", ""), ("PROFILE", "Profile", "")),
        default="NORMAL", update=_on_soft_inflation_update,
    )
    inflation_amount: bpy.props.FloatProperty(name="Amount", default=0.2, min=0.0, update=_on_soft_tissue_prop_update)
    minimum_amount: bpy.props.FloatProperty(name="Minimum", default=0.0, min=0.0, update=_on_soft_tissue_prop_update)
    axis_scale: bpy.props.FloatVectorProperty(name="Axis Scale", size=3, default=(1.0, 1.0, 1.0), min=0.001, update=_on_soft_tissue_prop_update)
    field_attribute: bpy.props.StringProperty(name="Inflation Field", default="AF_ST_INFLATION", update=_on_soft_tissue_prop_update)
    field_power: bpy.props.FloatProperty(name="Field Power", default=1.0, min=0.01, update=_on_soft_tissue_prop_update)
    profile_width: bpy.props.FloatProperty(name="Profile Width", default=0.08, min=0.001, update=_on_soft_tissue_prop_update)
    profile_power: bpy.props.FloatProperty(name="Profile Power", default=0.65, min=0.01, update=_on_soft_tissue_prop_update)
    profile_segments: bpy.props.IntProperty(name="Profile Segments", default=9, min=3, max=64, update=_on_soft_rest_topology_update)
    endpoint_taper: bpy.props.FloatProperty(name="Endpoint Taper", default=0.16, min=0.0, max=1.0, update=_on_soft_tissue_prop_update)
    shape_retention: bpy.props.FloatProperty(name="Shape Retention", description="Membrane tension and semisolid shape memory; higher values resist stretching and sag", default=0.5, min=0.0, max=1.0, update=_on_soft_tissue_prop_update)
    volume_retention: bpy.props.FloatProperty(name="Volume Retention", description="Incompressibility of the sealed tissue envelope", default=0.9, min=0.0, max=1.0, update=_on_soft_tissue_prop_update)
    surface_slack: bpy.props.FloatProperty(name="Surface Slack", description="Extra membrane length available before the surface becomes taut", default=0.0, min=0.0, max=1.0, subtype="FACTOR", update=_on_soft_tissue_prop_update)
    relaxation_mode: bpy.props.EnumProperty(
        name="Relaxation", items=(("NONE", "None", ""), ("GEOMETRIC", "Geometric", ""),
        ("STATIC_PBD", "Static PBD", "")), default="NONE", update=_on_soft_tissue_prop_update,
    )
    sagginess: bpy.props.FloatProperty(name="Sagginess", description="Direct sag amount in Geometric mode; gravity strength in Static PBD", default=0.35, min=0.0, max=1.0, update=_on_soft_tissue_prop_update)
    gravity: bpy.props.FloatVectorProperty(name="Gravity", size=3, default=(0.0, 0.0, -1.0), update=_on_soft_tissue_prop_update)
    sag_limit: bpy.props.FloatProperty(name="Sag Limit", default=0.0, min=0.0, update=_on_soft_tissue_prop_update)
    iterations: bpy.props.IntProperty(name="Iterations", default=24, min=1, max=1000, update=_on_soft_tissue_prop_update)
    constraint_passes: bpy.props.IntProperty(name="Constraint Passes", default=2, min=1, max=16, update=_on_soft_tissue_prop_update)
    tolerance: bpy.props.FloatProperty(name="Tolerance", description="Solver convergence threshold; automatically capped relative to gravity", default=1.0e-5, min=1.0e-9, max=1.0e-2, update=_on_soft_tissue_prop_update)
    attachments: bpy.props.CollectionProperty(type=AF_SoftTissueAttachment_Property)
    active_attachment_index: bpy.props.IntProperty(name="Active Attachment", default=-1)
    auto_recompute: bpy.props.BoolProperty(name="Auto Recompute", default=True, update=_on_soft_tissue_prop_update)
    show_rest: bpy.props.BoolProperty(name="Show Rest Shape", default=False, update=_on_soft_rest_update)


class AF_VCP_System_Property(bpy.types.PropertyGroup):
    authored_points: bpy.props.CollectionProperty(type=AF_AuthoredPoint_Property)
    point_schema_version: bpy.props.IntProperty(default=0)
    muscles: bpy.props.CollectionProperty(type=AF_MuscleVCP_Property)
    fibers: bpy.props.CollectionProperty(type=AF_FiberVCP_Property)
    fiber_surfaces: bpy.props.CollectionProperty(type=AF_FiberSurfaceVCP_Property)
    blobs: bpy.props.CollectionProperty(type=AF_BlobVCP_Property)
    soft_tissues: bpy.props.CollectionProperty(type=AF_SoftTissueVCP_Property)

    active_vcp_id: bpy.props.StringProperty(name="Active VCP ID", default="")
    active_vcp_type: bpy.props.EnumProperty(
        name="Active VCP Type",
        items=(
            ("NONE", "None", ""),
            ("MUSCLE", "Muscle", ""),
            ("FIBER", "Fiber", ""),
            ("FIBER_SURFACE", "Fiber Surface", ""),
            ("BLOB", "Blob", ""),
            ("SOFT_TISSUE", "Soft Tissue", ""),
        ),
        default="NONE",
    )

