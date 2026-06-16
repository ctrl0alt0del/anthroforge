def raw_target_value(target):
    return _custom_value(target) if _is_custom(target) else getattr(target.owner, target.prop_name)


def target_value(target):
    value = raw_target_value(target)
    return value if int(getattr(target, "index", -1)) < 0 else list(value)[int(target.index)]


def write_target_value(target, value):
    return _write_custom(target, value) if _is_custom(target) else _write_rna(target, value)


def _write_rna(target, value):
    if int(getattr(target, "index", -1)) < 0:
        setattr(target.owner, target.prop_name, value)
        return
    getattr(target.owner, target.prop_name)[int(target.index)] = value


def _write_custom(target, value):
    key = _custom_key(target.prop_name)
    _assign_custom_value(target.owner, key, int(getattr(target, "index", -1)), value)
    _refresh_custom_owner(target.owner)


def _assign_custom_value(owner, key, index, value):
    if index < 0:
        owner[key] = value
        return
    values = list(owner.get(key, ()))
    values[index] = value
    owner[key] = values


def _refresh_custom_owner(owner):
    obj = _nodes_owner_object(owner)
    obj.update_tag() if obj is not None else None


def _nodes_owner_object(owner):
    obj = getattr(owner, "id_data", None)
    kind = str(getattr(owner, "type", "") or "").upper()
    return obj if kind == "NODES" and hasattr(obj, "update_tag") else None


def _is_custom(target):
    return str(getattr(target, "prop_name", "") or "").startswith('["')


def _custom_key(prop_name):
    return str(prop_name or "")[2:-2]


def _custom_value(target):
    return target.owner.get(_custom_key(target.prop_name))
