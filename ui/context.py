from ..core.utils import get_af_root


def get_active_af_entity(root, context):
    obj = context.active_object

    if obj and obj.get("af_root_name") == root.name:
        if obj.get("af_proxy") and obj.get("af_scp_id"):
            return "SCP", obj.get("af_scp_id")

        if obj.get("af_fiber_proxy") and obj.get("af_fiber_id"):
            return "FIBER", obj.get("af_fiber_id")

        if obj.get("af_muscle_proxy") and obj.get("af_muscle_id"):
            return "MUSCLE", obj.get("af_muscle_id")

        if obj.get("af_blob_proxy") and obj.get("af_blob_id"):
            return "BLOB", obj.get("af_blob_id")

        if obj.get("af_fiber_endpoint_handle") and obj.get("af_fiber_id"):
            return "FIBER", obj.get("af_fiber_id")
        if obj.get("af_fiber_touch_handle") and obj.get("af_fiber_id"):
            return "FIBER", obj.get("af_fiber_id")

        if obj.get("af_muscle_inflation_ctrl") and obj.get("af_muscle_id"):
            return "MUSCLE", obj.get("af_muscle_id")

        if obj.get("af_blob_control_gizmo") and obj.get("af_blob_id"):
            return "BLOB", obj.get("af_blob_id")

        if obj.get("af_curve_point_handle") and obj.get("af_scp_id"):
            return "SCP", obj.get("af_scp_id")

        if obj.get("af_parallelepiped_vert_handle") and obj.get("af_scp_id"):
            return "SCP", obj.get("af_scp_id")

    idx = root.af_scp_system.active_scp_index
    if 0 <= idx < len(root.af_scp_system.scps):
        return "SCP", root.af_scp_system.scps[idx].id

    v = root.af_vcp_system
    if v.active_vcp_type in {"FIBER", "MUSCLE", "BLOB"} and v.active_vcp_id:
        return v.active_vcp_type, v.active_vcp_id

    return "NONE", ""


def get_active_scp(root, context):
    kind, entity_id = get_active_af_entity(root, context)
    if kind != "SCP":
        return None
    for scp in root.af_scp_system.scps:
        if scp.id == entity_id:
            return scp
    return None
