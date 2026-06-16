_FLOAT_SCALAR = {
    "ANGLE", "DISTANCE", "DISTANCE_CAMERA", "FACTOR", "PERCENTAGE",
    "PIXEL", "POWER", "TEMPERATURE", "TIME", "TIME_ABSOLUTE", "UNSIGNED",
}
_FLOAT_VECTOR = {
    "ACCELERATION", "AXISANGLE", "COLOR", "COLOR_GAMMA", "COORDINATES",
    "DIRECTION", "EULER", "QUATERNION", "TRANSLATION", "VELOCITY", "XYZ",
}

from .vector_modes import is_uniform_vector_shortcut


def proxy_prop_name(target, index=None):
    _ = index
    return _array_prop_name(target) if _whole_array(target) else _scalar_prop_name(target)


def shortcut_prop_name(shortcut, target, index=None):
    direct = index is None and is_uniform_vector_shortcut(shortcut, target)
    return _uniform_prop_name(target) if direct else proxy_prop_name(target, index=index)


def _is_array(target):
    return int(getattr(target, "array_length", 0) or 0) > 0


def _whole_array(target):
    return _is_array(target) and int(getattr(target, "index", -1)) < 0


def _array_prop_name(target):
    value_type = str(getattr(target, "value_type", "") or "").upper()
    if value_type == "BOOL":
        return "proxy_bool_vec"
    if value_type == "INT":
        return "proxy_int_vec"
    return _float_vector_name(getattr(target, "subtype", "")) if value_type == "FLOAT" else "proxy_float_vec"


def _scalar_prop_name(target):
    value_type = str(getattr(target, "value_type", "") or "").upper()
    if value_type == "BOOL":
        return "proxy_bool"
    if value_type == "INT":
        return "proxy_int"
    if value_type == "FLOAT":
        return _float_scalar_name(getattr(target, "subtype", ""))
    return "proxy_enum" if value_type == "ENUM" else "proxy_string"


def _uniform_prop_name(target):
    value_type = str(getattr(target, "value_type", "") or "").upper()
    return "proxy_int" if value_type == "INT" else _float_scalar_name(getattr(target, "subtype", ""))


def _float_scalar_name(subtype):
    kind = _scalar_subtype(subtype)
    return "proxy_float" if not kind else f"proxy_float_{kind.lower()}"


def _float_vector_name(subtype):
    kind = _vector_subtype(subtype)
    return "proxy_float_vec" if not kind else f"proxy_float_vec_{kind.lower()}"


def _scalar_subtype(subtype):
    kind = _subtype_name(subtype)
    kind = "ANGLE" if kind == "EULER" else kind
    return kind if kind in _FLOAT_SCALAR else ""


def _vector_subtype(subtype):
    kind = _subtype_name(subtype)
    kind = "EULER" if kind == "ANGLE" else kind
    return kind if kind in _FLOAT_VECTOR else ""


def _subtype_name(subtype):
    return str(subtype or "").upper()
