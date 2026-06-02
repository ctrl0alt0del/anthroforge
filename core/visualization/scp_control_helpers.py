def mark_scp_control_object(obj, root, scp_id):
    if obj is None or root is None:
        return None
    sid = str(scp_id or "").strip()
    if not sid:
        return None
    obj["af_scp_control"] = True
    obj["af_root_name"] = str(getattr(root, "name", "") or "")
    obj["af_scp_id"] = sid
    return obj


def mark_scp_curve_point_control(obj, root, scp_id, point_index):
    marked = mark_scp_control_object(obj, root, scp_id)
    if marked is None:
        return None
    marked["af_curve_point_handle"] = True
    marked["af_curve_point_index"] = int(point_index)
    return marked


def mark_scp_parallelepiped_vertex_control(obj, root, scp_id, vert_index):
    marked = mark_scp_control_object(obj, root, scp_id)
    if marked is None:
        return None
    marked["af_parallelepiped_vert_handle"] = True
    marked["af_parallelepiped_vert_index"] = int(vert_index)
    return marked


def clear_scp_control_marks(obj):
    if obj is None:
        return
    for key in (
        "af_scp_control",
        "af_root_name",
        "af_scp_id",
        "af_curve_point_handle",
        "af_curve_point_index",
        "af_parallelepiped_vert_handle",
        "af_parallelepiped_vert_index",
    ):
        if key in obj:
            del obj[key]
