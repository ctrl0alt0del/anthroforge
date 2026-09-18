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


def apply_scalar_dict(prop, values, *, geometry_scale=1):
    if values and "section_profile_version" in values:
        from .muscle_profile import prepared_properties
        values = prepared_properties(values, geometry_scale)
    values = dict(values or {})
    for key, value in sorted(values.items(), key=lambda row: row[0] == "inflation_mode"):
        if hasattr(prop, key):
            setattr(prop, key, value)
