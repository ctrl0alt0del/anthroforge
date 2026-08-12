from ..queries.root import root_for_context
from ..queries.vcp import active_soft_tissue_from_context
from .results import failure, success
try:
    from ...core.vcp.attachment_backend import attachment_runtime
    from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from ...core.vcp.runtime_state import (
        set_soft_tissue_diagnostic, set_soft_tissue_status, soft_tissue_diagnostic, soft_tissue_status,
    )
    from ...core.vcp.surface_target import SurfaceTargetKind, effective_tissue_target, target_ref
    from ...core.visualization.surface_target_service import default_surface_target_service
    from ...core.visualization.vcp_mirror_runtime import surface_target_mirror_rule, tissue_source_mirror_rule
except ImportError:
    from core.vcp.attachment_backend import attachment_runtime
    from core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from core.vcp.runtime_state import (
        set_soft_tissue_diagnostic, set_soft_tissue_status, soft_tissue_diagnostic, soft_tissue_status,
    )
    from core.vcp.surface_target import SurfaceTargetKind, effective_tissue_target, target_ref
    from core.visualization.surface_target_service import default_surface_target_service
    from core.visualization.vcp_mirror_runtime import surface_target_mirror_rule, tissue_source_mirror_rule


def assign_soft_tissue_target(context, target_type="", target_id="", surface="", tissue_id=""):
    root = root_for_context(context)
    tissue = _target_tissue(context, root, tissue_id)
    obj = getattr(context.scene, "af_new_soft_tissue_target_obj", None)
    if tissue is None or root is None:
        return failure("Soft Tissue VCP not found.")
    ref, error = _assignment_ref(root, obj, target_type, target_id, surface)
    if error:
        return failure(error)
    return _change_target(context, root, tissue, ref, "Assigned Soft Tissue target.")


def _assignment_ref(root, obj, target_type, target_id, surface):
    kind = str(target_type or "")
    if kind in {"", "PICKER"}:
        return target_ref_from_object(root, obj)
    default = "MUSCLE_INFL" if kind == "MUSCLE" else "SCP_GEOMETRY"
    role = default if str(surface or "DEFAULT") == "DEFAULT" else str(surface)
    return target_ref(kind, target_id, role), ""


def clear_soft_tissue_target(context, tissue_id=""):
    root = root_for_context(context)
    tissue = _target_tissue(context, root, tissue_id)
    if tissue is None or root is None:
        return failure("Soft Tissue VCP not found.")
    return _change_target(context, root, tissue, target_ref(), "Cleared Soft Tissue target.")


def select_soft_tissue_target(context, tissue_id=""):
    root = root_for_context(context)
    tissue = _target_tissue(context, root, tissue_id)
    if tissue is None or root is None:
        return failure("Soft Tissue VCP not found.")
    resolved = _resolve_current_target(root, context.scene, tissue)
    if resolved is None:
        return failure("Soft Tissue has no attachment target.")
    _select_only(context, resolved.mesh_object)
    return success(value=resolved.mesh_object)


def _target_tissue(context, root, tissue_id):
    if root is None or not tissue_id:
        return active_soft_tissue_from_context(context)
    return next((item for item in root.af_vcp_system.soft_tissues if item.id == tissue_id), None)


def target_ref_from_object(root, obj):
    if obj is None:
        return target_ref(), "Select an SCP geometry or original Muscle surface."
    if root is None or obj.get("af_root_name") != root.name:
        return target_ref(), "Attachment target must belong to the active AnthroForge root."
    if obj.get("af_scp_geometry") and not obj.get("af_scp_mirror"):
        return target_ref("SCP", obj.get("af_scp_id"), "SCP_GEOMETRY"), ""
    return _muscle_ref_from_object(obj)


def _muscle_ref_from_object(obj):
    if not obj.get("af_muscle_proxy") or obj.get("af_muscle_mirror_proxy"):
        return target_ref(), "Target must be an original SCP geometry or Muscle surface."
    roles = {"BASE": "MUSCLE_BASE", "INFL": "MUSCLE_INFL"}
    surface = roles.get(str(obj.get("af_muscle_surface", "")))
    if surface is None:
        return target_ref(), "Muscle target surface role is missing."
    return target_ref("MUSCLE", obj.get("af_muscle_id"), surface), ""


def _change_target(context, root, tissue, ref, message):
    mirror_error = _mirror_assignment_error(root, tissue, ref)
    if mirror_error:
        return failure(mirror_error)
    old = _target_snapshot(tissue)
    with suppress_vcp_prop_updates():
        _assign_target_fields(tissue, ref)
        _clear_binding_payloads(tissue)
    _sync_target(root, context.scene, tissue.id, True)
    if soft_tissue_status(tissue) != "ERROR":
        return success(message, value=tissue)
    error = soft_tissue_diagnostic(tissue)[3]
    _restore_target_snapshot(tissue, old)
    return failure(error or "Target assignment failed.")


def _mirror_assignment_error(root, tissue, target):
    source_rule = tissue_source_mirror_rule(root, tissue)
    target_rule = surface_target_mirror_rule(root, target)
    if source_rule is not None and target_rule is not None and source_rule != target_rule:
        return "Source and attachment target use incompatible mirror rules."
    return ""


def _assign_target_fields(tissue, ref):
    tissue.schema_version = 2
    tissue.attachment_target_type = ref.kind.value
    tissue.attachment_target_id = ref.entity_id
    tissue.attachment_target_surface = ref.surface.value
    tissue.attachment_topology_signature = ""


def _clear_binding_payloads(tissue):
    tissue.control_bindings_json = "[]"
    tissue.base_bindings_json = "[]"
    for row in tissue.attachments:
        row.bindings_json = "[]"


def _target_snapshot(tissue):
    keys = ("schema_version", "attachment_target_type", "attachment_target_id",
            "attachment_target_surface", "attachment_topology_signature",
            "control_bindings_json", "base_bindings_json")
    values = {key: getattr(tissue, key) for key in keys}
    values["regions"] = tuple(row.bindings_json for row in tissue.attachments)
    values["runtime"] = (soft_tissue_status(tissue), soft_tissue_diagnostic(tissue))
    return values


def _restore_target_snapshot(tissue, values):
    with suppress_vcp_prop_updates():
        for key, value in values.items():
            if key not in {"regions", "runtime"}:
                setattr(tissue, key, value)
        for row, raw in zip(tissue.attachments, values["regions"]):
            row.bindings_json = raw
    _restore_runtime(tissue, values["runtime"])


def _restore_runtime(tissue, values):
    status, diagnostic = values
    set_soft_tissue_status(tissue, status)
    set_soft_tissue_diagnostic(tissue, diagnostic[0], diagnostic[1], diagnostic[2], diagnostic[3])


def _sync_target(root, scene, tissue_id, recapture):
    try:
        from ...app.runtime_api import sync_scene
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from app.runtime_api import sync_scene
        from core.deps.dirty_hints import dirty_hints_for
    payload = {"soft_tissue_force": True}
    if recapture:
        payload["soft_tissue_recapture_ids"] = [str(tissue_id)]
    sync_scene(root, scene, dirty_hints_for("SOFT_TISSUE", {tissue_id}), source="operator",
               event_type="SOFT_TISSUE_UPDATE", payload=payload)
    root.af_vcp_system.active_vcp_type, root.af_vcp_system.active_vcp_id = "SOFT_TISSUE", str(tissue_id)


def _resolve_current_target(root, scene, tissue):
    ref = effective_tissue_target(tissue)
    if ref.kind == SurfaceTargetKind.NONE:
        return None
    return default_surface_target_service().resolve(root, scene, ref, attachment_runtime(scene))


def _select_only(context, obj):
    for selected in tuple(context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
