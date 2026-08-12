import bpy

from ..queries.root import root_for_context
from .results import failure, success
from ...core.id_utils import next_prefixed_id
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
from ...core.vcp.soft_tissue_presets import preset_values
from ...core.vcp.soft_tissue_surface_field import boundary_falloff_weights
from ...core.visualization.soft_tissue_source import infer_base_domain, validate_source


def create_soft_tissue_vcp(context):
    root, preset, source, domain, host, source_type, source_id = _creation_inputs(context)
    error = "No AF_ROOT found." if root is None else _preflight_source(root, source, domain, preset, source_type, source_id)
    if error:
        return failure(error)
    error = _preflight_host(host, preset)
    if error:
        return failure(error)
    source, owned = _ensure_source(context, source, preset) if source_type == "OBJECT" else (None, False)
    tissue = _create_record(root, source, owned, host, preset, source_type, source_id, domain)
    _ensure_surface_field(source, tissue.field_attribute)
    _activate(root, tissue)
    _sync_tissue(root, context.scene, tissue.id, True)
    return success(f"Added {tissue.id}", value=tissue)


def _creation_inputs(context):
    root = root_for_context(context)
    preset = str(context.scene.af_new_soft_tissue_preset)
    source_type, source_id, domain = _selected_entity_source(context, root)
    source = getattr(context.scene, "af_new_soft_tissue_base_obj", None) if source_type == "OBJECT" else None
    domain = domain or ("POINT" if source is None and preset == "CLOSED_BULK" else infer_base_domain(source))
    host = getattr(context.scene, "af_new_soft_tissue_host_obj", None)
    return root, preset, source, domain, host, source_type, source_id


def _selected_entity_source(context, root):
    obj = getattr(context, "active_object", None)
    if root is None or obj is None or obj.get("af_root_name") != root.name:
        return "OBJECT", "", ""
    if obj.get("af_fiber_surface_proxy"):
        return "FIBER_SURFACE", str(obj.get("af_fiber_surface_id") or ""), "SURFACE"
    if obj.get("af_fiber_proxy"):
        return "FIBER", str(obj.get("af_fiber_id") or ""), "CURVE"
    return "OBJECT", "", ""


def apply_soft_tissue_preset(context, preset, tissue=None):
    tissue = tissue or _active_tissue(context)
    if tissue is None:
        return failure("Soft Tissue VCP not found.")
    values = preset_values(preset)
    if str(preset) != "CUSTOM" and str(tissue.base_domain) != values.domain.value:
        return failure(f"{preset} requires a {values.domain.value.title()} base.")
    with suppress_vcp_prop_updates():
        _assign_preset(tissue, str(preset), values)
        if str(preset) == "CUSTOM":
            _assign_custom_domain(tissue)
    _sync_tissue(root_for_context(context), context.scene, tissue.id, True)
    return success(f"Applied {preset} preset.", value=tissue)


def _preflight_source(root, source, domain, preset, source_type="OBJECT", source_id=""):
    if source_type != "OBJECT":
        return _preflight_entity_source(root, source_type, source_id, domain, preset)
    if source is None and preset != "CLOSED_BULK":
        return "Select an Empty, Curve, or Mesh base object."
    if source is None:
        return ""
    errors = validate_source(source, domain)
    if errors:
        return " ".join(errors)
    owned = any(getattr(item, "base_object_ref", None) == source for item in root.af_vcp_system.soft_tissues)
    if source.get("af_soft_tissue_id") or owned:
        return "The selected base already belongs to a Soft Tissue VCP."
    required = preset_values(preset).domain.value
    return "" if preset == "CUSTOM" or domain == required else f"{preset} requires a {required.title()} base."


def _preflight_entity_source(root, source_type, source_id, domain, preset):
    collection = "fibers" if source_type == "FIBER" else "fiber_surfaces"
    found = any(str(item.id) == str(source_id) for item in getattr(root.af_vcp_system, collection, ()))
    if not found:
        return f"Selected {source_type.replace('_', ' ').title()} is missing."
    required = preset_values(preset).domain.value
    return "" if preset == "CUSTOM" or domain == required else f"{preset} requires a {required.title()} base."


def _preflight_host(host, preset):
    if preset in {"RIM", "LAYER", "POUCH"} and host is None:
        return "This preset requires a host SCP geometry object."
    if host is not None and not host.get("af_scp_geometry"):
        return "Host must be an SCP geometry object."
    return ""


def _ensure_source(context, source, preset):
    if source is not None:
        return source, False
    source = bpy.data.objects.new("AF_SOFT_TISSUE_POINT", None)
    source.location = context.scene.cursor.location
    context.scene.collection.objects.link(source)
    source.empty_display_type = "SPHERE"
    source.empty_display_size = 0.04
    return source, True


def _create_record(root, source, owned, host, preset, source_type="OBJECT", source_id="", domain=""):
    tissues = root.af_vcp_system.soft_tissues
    tissue = tissues.add()
    with suppress_vcp_prop_updates():
        tissue.id = next_prefixed_id(tissues, "TISSUE")
        tissue.name = tissue.id
        tissue.base_source_type, tissue.base_source_id = str(source_type), str(source_id)
        tissue.base_object_ref = source
        tissue.base_owned = bool(owned)
        tissue.base_domain = str(domain or infer_base_domain(source))
        tissue.host_scp_id = "" if host is None else str(host.get("af_scp_id", ""))
        _assign_preset(tissue, preset, preset_values(preset))
        if preset == "CUSTOM":
            _assign_custom_domain(tissue)
    return tissue


def _assign_preset(tissue, preset, values):
    tissue.preset = str(preset)
    tissue.boundary_mode = values.boundary.value
    tissue.inflation_mode = values.inflation_mode.value
    tissue.relaxation_mode = values.relaxation_mode.value
    for key, value in values.values:
        setattr(tissue, key, value)
    tissue.attachments.clear()
    for mask, mode, strength in values.attachments:
        row = tissue.attachments.add()
        row.mask_attribute, row.mode, row.strength = mask, mode, strength


def _assign_custom_domain(tissue):
    domain = str(tissue.base_domain)
    tissue.inflation_mode = {"POINT": "RADIAL", "CURVE": "PROFILE", "SURFACE": "NORMAL"}[domain]
    tissue.boundary_mode = "CLOSED" if domain == "POINT" else "HOST_SEALED"


def _ensure_surface_field(source, name):
    if source is None or source.type != "MESH" or source.vertex_groups.get(name) is not None:
        return
    mesh = source.data
    edges = tuple(tuple(edge.vertices) for edge in mesh.edges)
    faces = tuple(tuple(poly.vertices) for poly in mesh.polygons)
    vertices = tuple(tuple(vertex.co) for vertex in mesh.vertices)
    weights = boundary_falloff_weights(len(mesh.vertices), edges, faces, vertices)
    group = source.vertex_groups.new(name=name)
    for index, weight in enumerate(weights):
        group.add([index], float(weight), "REPLACE")


def _active_tissue(context):
    root = root_for_context(context)
    if root is None or root.af_vcp_system.active_vcp_type != "SOFT_TISSUE":
        return None
    target = str(root.af_vcp_system.active_vcp_id)
    return next((item for item in root.af_vcp_system.soft_tissues if item.id == target), None)


def _activate(root, tissue):
    root.af_vcp_system.active_vcp_type = "SOFT_TISSUE"
    root.af_vcp_system.active_vcp_id = str(tissue.id)


def _sync_tissue(root, scene, tissue_id, recapture):
    from ...app.runtime_api import sync_scene
    from ...core.deps.dirty_hints import dirty_hints_for
    payload = {"soft_tissue_force": True}
    if recapture:
        payload["soft_tissue_recapture_ids"] = [str(tissue_id)]
    sync_scene(root, scene, dirty_hints_for("SOFT_TISSUE", {tissue_id}), source="operator",
               event_type="SOFT_TISSUE_UPDATE", payload=payload)
