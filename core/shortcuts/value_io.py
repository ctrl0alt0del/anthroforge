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
    if int(getattr(target, "index", -1)) < 0:
        target.owner[key] = value
        return
    values = list(target.owner.get(key, ()))
    values[int(target.index)] = value
    target.owner[key] = values


def _is_custom(target):
    return str(getattr(target, "prop_name", "") or "").startswith('["')


def _custom_key(prop_name):
    return str(prop_name or "")[2:-2]


def _custom_value(target):
    return target.owner.get(_custom_key(target.prop_name))
