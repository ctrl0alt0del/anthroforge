_BUILTIN_CONTROL_FLAGS = (
    "af_scp_control",
    "af_curve_point_handle",
    "af_parallelepiped_vert_handle",
    "af_fiber_endpoint_handle",
    "af_fiber_touch_handle",
    "af_fiber_loop_anchor_handle",
    "af_muscle_inflation_ctrl",
    "af_blob_control_gizmo",
)
_CONTROL_FLAG_KEYS = ()


def set_control_flag_keys(keys):
    global _CONTROL_FLAG_KEYS
    _CONTROL_FLAG_KEYS = tuple(keys or ())


def control_flag_keys():
    return _CONTROL_FLAG_KEYS or _BUILTIN_CONTROL_FLAGS


def is_control_object(obj):
    if obj is None:
        return False
    for key in control_flag_keys():
        try:
            if obj.get(key):
                return True
        except Exception:
            continue
    return False
