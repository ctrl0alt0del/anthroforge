def _entity_from_active_object(root_name, obj):
    if not obj or obj.get("af_root_name") != root_name:
        return None
    checks = (
        ("af_proxy", "af_scp_id", "SCP"),
        ("af_fiber_proxy", "af_fiber_id", "FIBER"),
        ("af_muscle_proxy", "af_muscle_id", "MUSCLE"),
        ("af_blob_proxy", "af_blob_id", "BLOB"),
        ("af_fiber_endpoint_handle", "af_fiber_id", "FIBER"),
        ("af_fiber_touch_handle", "af_fiber_id", "FIBER"),
        ("af_muscle_inflation_ctrl", "af_muscle_id", "MUSCLE"),
        ("af_blob_control_gizmo", "af_blob_id", "BLOB"),
        ("af_curve_point_handle", "af_scp_id", "SCP"),
        ("af_parallelepiped_vert_handle", "af_scp_id", "SCP"),
    )
    for flag, id_key, kind in checks:
        if obj.get(flag) and obj.get(id_key):
            return kind, obj.get(id_key)
    return None


def _active_scp_from_tree(root):
    idx = root.af_scp_system.active_scp_index
    if 0 <= idx < len(root.af_scp_system.scps):
        return "SCP", root.af_scp_system.scps[idx].id
    return None


def _active_vcp_from_tree(root):
    v = root.af_vcp_system
    if v.active_vcp_type in {"FIBER", "MUSCLE", "BLOB"} and v.active_vcp_id:
        return v.active_vcp_type, v.active_vcp_id
    return None


def get_active_af_entity(root, context):
    direct = _entity_from_active_object(root.name, context.active_object)
    if direct is not None:
        return direct
    active_scp = _active_scp_from_tree(root)
    if active_scp is not None:
        return active_scp
    active_vcp = _active_vcp_from_tree(root)
    if active_vcp is not None:
        return active_vcp
    return "NONE", ""


def get_active_scp(root, context):
    kind, entity_id = get_active_af_entity(root, context)
    if kind != "SCP":
        return None
    for scp in root.af_scp_system.scps:
        if scp.id == entity_id:
            return scp
    return None
