_FIELDS = {
    "attach_initialized": ("_af_rt_scp_attach_initialized", False),
    "attach_parent_tri_vidx": ("_af_rt_scp_attach_parent_tri_vidx", (-1, -1, -1)),
    "attach_parent_tri_weights": ("_af_rt_scp_attach_parent_tri_weights", (1.0, 0.0, 0.0)),
    "attach_parent_offset_local": ("_af_rt_scp_attach_parent_offset_local", (0.0, 0.0, 0.0)),
    "attach_parent_tangent_hint_local": ("_af_rt_scp_attach_parent_tangent_hint_local", (1.0, 0.0, 0.0)),
    "attach_parent_flow_tri_vidx": ("_af_rt_scp_attach_parent_flow_tri_vidx", (-1, -1, -1)),
    "attach_parent_flow_tri_weights": ("_af_rt_scp_attach_parent_flow_tri_weights", (1.0, 0.0, 0.0)),
    "attach_child_anchor_index": ("_af_rt_scp_attach_child_anchor_index", -1),
    "attach_child_origin_local": ("_af_rt_scp_attach_child_origin_local", (0.0, 0.0, 0.0)),
    "attach_child_tangent_local": ("_af_rt_scp_attach_child_tangent_local", (1.0, 0.0, 0.0)),
    "attach_child_normal_local": ("_af_rt_scp_attach_child_normal_local", (0.0, 0.0, 1.0)),
}
_MIRROR_STATUS = "_af_rt_scp_mirror_status"
_MIRROR_SOURCE = "_af_rt_scp_mirror_source_id"
_MIRROR_AXIS = "_af_rt_scp_mirror_effective_axis"

_INT3 = {"attach_parent_tri_vidx", "attach_parent_flow_tri_vidx"}
_FLOAT3 = {
    "attach_parent_tri_weights",
    "attach_parent_offset_local",
    "attach_parent_tangent_hint_local",
    "attach_parent_flow_tri_weights",
    "attach_child_origin_local",
    "attach_child_tangent_local",
    "attach_child_normal_local",
}


def attach_initialized(scp):
    return bool(read_attachment_runtime(scp, "attach_initialized"))


def set_attach_initialized(scp, value):
    write_attachment_runtime(scp, "attach_initialized", bool(value))


def attach_child_anchor_index(scp):
    return int(read_attachment_runtime(scp, "attach_child_anchor_index"))


def set_attach_child_anchor_index(scp, value):
    write_attachment_runtime(scp, "attach_child_anchor_index", int(value))


def attach_child_origin_local(scp):
    return read_attachment_runtime(scp, "attach_child_origin_local")


def attach_child_tangent_local(scp):
    return read_attachment_runtime(scp, "attach_child_tangent_local")


def attach_child_normal_local(scp):
    return read_attachment_runtime(scp, "attach_child_normal_local")


def attach_parent_offset_local(scp):
    return read_attachment_runtime(scp, "attach_parent_offset_local")


def attach_parent_tangent_hint_local(scp):
    return read_attachment_runtime(scp, "attach_parent_tangent_hint_local")


def attach_parent_param(scp):
    return _param(read_attachment_runtime(scp, "attach_parent_tri_vidx"), read_attachment_runtime(scp, "attach_parent_tri_weights"))


def set_attach_parent_param(scp, param):
    _set_param(scp, "attach_parent_tri_vidx", "attach_parent_tri_weights", param)


def attach_flow_param(scp):
    return _param(read_attachment_runtime(scp, "attach_parent_flow_tri_vidx"), read_attachment_runtime(scp, "attach_parent_flow_tri_weights"))


def set_attach_flow_param(scp, param):
    _set_param(scp, "attach_parent_flow_tri_vidx", "attach_parent_flow_tri_weights", param)


def read_attachment_runtime(scp, name):
    default = _default(name)
    value = _read(scp, _key(name), default)
    return _coerce(name, value, default)


def write_attachment_runtime(scp, name, value):
    _write(scp, _key(name), _coerce(name, value, _default(name)))


def snapshot_attachment_runtime(scp):
    return {name: read_attachment_runtime(scp, name) for name in _FIELDS}


def restore_attachment_runtime(scp, snapshot):
    values = dict(snapshot or {})
    for name in _FIELDS:
        write_attachment_runtime(scp, name, values.get(name, _default(name)))


def reset_attachment_runtime(scp):
    restore_attachment_runtime(scp, {})


def mirror_status(scp):
    return _status(_read(scp, _MIRROR_STATUS, "NONE"))


def set_mirror_status(scp, value):
    _write(scp, _MIRROR_STATUS, _status(value))


def mirror_source_id(scp):
    return str(_read(scp, _MIRROR_SOURCE, "") or "")


def set_mirror_source_id(scp, value):
    _write(scp, _MIRROR_SOURCE, str(value or ""))


def mirror_effective_axis(scp):
    return _axis(_read(scp, _MIRROR_AXIS, "X"))


def set_mirror_effective_axis(scp, value):
    _write(scp, _MIRROR_AXIS, _axis(value))


def reset_mirror_runtime(scp):
    set_mirror_status(scp, "NONE")
    set_mirror_source_id(scp, "")
    set_mirror_effective_axis(scp, "X")


def reset_scp_runtime_state(root):
    system = None if root is None else getattr(root, "af_scp_system", None)
    if system is None:
        return
    for scp in getattr(system, "scps", ()):
        reset_attachment_runtime(scp)
        reset_mirror_runtime(scp)


def _param(tri, weights):
    return None if min(tri) < 0 else {"tri_vidx": tri, "tri_weights": weights}


def _set_param(scp, tri_key, weight_key, param):
    tri = (-1, -1, -1) if param is None else tuple(int(v) for v in param["tri_vidx"])
    weights = (1.0, 0.0, 0.0) if param is None else tuple(float(v) for v in param["tri_weights"])
    write_attachment_runtime(scp, tri_key, tri)
    write_attachment_runtime(scp, weight_key, weights)


def _key(name):
    return _FIELDS[str(name)][0]


def _default(name):
    return _FIELDS[str(name)][1]


def _coerce(name, value, default):
    if name == "attach_initialized":
        return bool(value)
    if name == "attach_child_anchor_index":
        return int(value)
    if name in _INT3:
        return _tuple3(value, int, default)
    if name in _FLOAT3:
        return _tuple3(value, float, default)
    return default if value is None else value


def _tuple3(value, cast, default):
    try:
        data = tuple(value)
    except Exception:
        data = tuple(default)
    return tuple(cast(data[i] if i < len(data) else default[i]) for i in range(3))


def _read(prop, key, default):
    try:
        value = prop.get(key, default)
    except Exception:
        value = getattr(prop, key, default)
    return default if value is None else value


def _write(prop, key, value):
    stored = list(value) if isinstance(value, (list, tuple)) else value
    try:
        prop[key] = stored
    except Exception:
        setattr(prop, key, stored)


def _axis(value):
    axis = str(value or "").upper()
    return axis if axis in {"X", "Y", "Z"} else "X"


def _status(value):
    status = str(value or "").upper()
    return status if status in {"NONE", "SOURCE", "TARGET"} else "NONE"
