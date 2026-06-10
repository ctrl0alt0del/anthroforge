def _json_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return [_json_value(item) for item in value]


def _scalar_keys(prop, skip=()):
    blocked = set(skip or ())
    for item in prop.bl_rna.properties:
        key = item.identifier
        if key == "rna_type" or key in blocked or item.is_readonly:
            continue
        if item.type in {"POINTER", "COLLECTION"}:
            continue
        yield key


def scalar_dict(prop, skip=()):
    return {key: _json_value(getattr(prop, key)) for key in _scalar_keys(prop, skip)}


def apply_scalar_dict(prop, values):
    for key, value in dict(values or {}).items():
        if hasattr(prop, key):
            setattr(prop, key, value)
