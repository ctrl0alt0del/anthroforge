import json

from ..queries.root import root_for_context

try:
    from ...core.shortcuts import override_values, raw_target_value, resolve_shortcut, target_value, upsert_override, write_target_value
    from ...core.shortcuts.proxy_props import shortcut_prop_name
    from ...core.shortcuts.vector_modes import is_uniform_vector_shortcut
    from ...core.shortcuts.owners import selected_scp_id, shortcut_relation
    from ...core.shortcuts.session_state import begin_override_session, clear_override_session, suppress_next_depsgraph_ids
    from ...core.scp_runtime.common import find_scp_by_id
except ImportError:
    from core.shortcuts import override_values, raw_target_value, resolve_shortcut, target_value, upsert_override, write_target_value
    from core.shortcuts.proxy_props import shortcut_prop_name
    from core.shortcuts.vector_modes import is_uniform_vector_shortcut
    from core.shortcuts.owners import selected_scp_id, shortcut_relation
    from core.shortcuts.session_state import begin_override_session, clear_override_session, suppress_next_depsgraph_ids
    from core.scp_runtime.common import find_scp_by_id


def apply_shortcut_proxy(context, shortcut):
    target = resolve_shortcut_target(context, shortcut)
    return False if target is None else _apply_target(context, root_for_context(context), shortcut, target)


def resolve_shortcut_target(context, shortcut):
    root = root_for_context(context)
    if root is None or bool(getattr(shortcut, "proxy_sync_lock", False)):
        return None
    return resolve_shortcut(root, context, getattr(shortcut, "data_path", ""))


def apply_shortcut_value(context, shortcut, value):
    target = resolve_shortcut_target(context, shortcut)
    root = root_for_context(context)
    return False if target is None or root is None else _apply_target_value(context, root, shortcut, target, value)


def _apply_target(context, root, shortcut, target):
    if getattr(target, "owner", None) is None:
        return False
    return _apply_target_value(context, root, shortcut, target, proxy_value(shortcut, target))


def _apply_target_value(context, root, shortcut, target, value):
    value = _target_write_value(shortcut, target, value)
    return _apply_scp_session(context, root, shortcut, target, value) if str(getattr(shortcut, "owner_type", "")) == "SCP" else _write_plain(target, value)


def _write_plain(target, value):
    write_target_value(target, value)
    return True


def _apply_scp_session(context, root, shortcut, target, value):
    scp_id, relation = _session_target(root, context, shortcut)
    values = _session_values(shortcut, scp_id, relation)
    payload, dirty_ids = _session_sync(shortcut, scp_id, relation, root, values)
    begin_override_session(scp_id, *values)
    suppress_next_depsgraph_ids({getattr(shortcut, "owner_id", "")})
    try:
        write_target_value(target, value)
        _sync_context()(context, dirty_hints=_dirty_hints_for()("SCP", dirty_ids), source="shortcut", event_type="UPDATE", payload=payload)
    finally:
        clear_override_session()
    return True


def _session_target(root, context, shortcut):
    scp_id = selected_scp_id(root, context)
    return scp_id, shortcut_relation(root, shortcut, scp_id)


def _session_values(shortcut, scp_id, relation):
    return override_values(shortcut, scp_id) if relation == "ANCESTOR" else _keep_values()


def _session_sync(shortcut, scp_id, relation, root, values):
    recapture = _recapture_ids(root, scp_id, relation, values)
    return _session_payload(shortcut, recapture), _session_dirty_ids(shortcut, recapture)


def _session_payload(shortcut, recapture):
    owner_id = str(getattr(shortcut, "owner_id", "") or "")
    return {"scp_apply_parent_ids": [owner_id], "scp_recapture_ids": sorted(recapture)}


def _session_dirty_ids(shortcut, recapture):
    owner_id = str(getattr(shortcut, "owner_id", "") or "")
    return {sid for sid in ({owner_id} | set(recapture or set())) if sid}


def _recapture_ids(root, scp_id, relation, values):
    if not _needs_session_recapture(values):
        return set()
    scp = find_scp_by_id(root, scp_id)
    valid = relation in {"SELF", "ANCESTOR"} and str(getattr(scp, "parent_id", "") or "")
    return {str(scp_id or "")} if valid else set()


def _needs_session_recapture(values):
    return _anchor_override(values) or _strategy_override(values)


def _anchor_override(values):
    return any(str(value or "KEEP") != "KEEP" for value in tuple(values or ())[:2])


def _strategy_override(values):
    data = tuple(values or ())
    return len(data) > 3 and str(data[3] or "KEEP") != "KEEP"


def _keep_values():
    return ("KEEP", "KEEP", "KEEP", "KEEP")


def proxy_value(shortcut, target):
    return _proxy_array_value(shortcut, target) if _uses_array_proxy(shortcut, target) else _proxy_scalar_value(shortcut, target)


def _proxy_scalar_value(shortcut, target):
    return getattr(shortcut, shortcut_prop_name(shortcut, target), "")


def _proxy_array_value(shortcut, target):
    values = _proxy_array(shortcut, getattr(target, "value_type", ""), int(getattr(target, "array_length", 0) or 0))
    return tuple(values) if int(getattr(target, "index", -1)) < 0 else values[int(target.index)]


def _proxy_array(shortcut, value_type, length):
    source = _proxy_array_source(shortcut, value_type)
    caster = bool if value_type == "BOOL" else int if value_type == "INT" else float
    return [caster(source[index]) for index in range(min(length, len(source)))]


def _proxy_array_source(shortcut, value_type):
    names = {"BOOL": "proxy_bool_vec", "INT": "proxy_int_vec", "FLOAT": "proxy_float_vec"}
    return tuple(getattr(shortcut, names.get(value_type, "proxy_float_vec"), ()))


def _uses_array_proxy(shortcut, target):
    size = int(getattr(target, "array_length", 0) or 0)
    return size > 0 and not is_uniform_vector_shortcut(shortcut, target)


def _target_write_value(shortcut, target, value):
    return _uniform_write_value(target, value) if is_uniform_vector_shortcut(shortcut, target) else value


def _uniform_write_value(target, value):
    caster = int if str(getattr(target, "value_type", "")).upper() == "INT" else float
    scalar = _uniform_scalar(value)
    size = int(getattr(target, "array_length", 0) or 0)
    return tuple(caster(scalar) for _ in range(size))


def _live_target_value(shortcut, target):
    value = target_value(target)
    return _uniform_scalar(value) if is_uniform_vector_shortcut(shortcut, target) else value


def _uniform_scalar(value):
    data = tuple(value) if hasattr(value, "__len__") and not isinstance(value, (str, bytes)) else ()
    return data[0] if data else value


def prime_shortcut_proxy(shortcut, target):
    if getattr(target, "owner", None) is None:
        return False
    _set_proxy(shortcut, "proxy_sync_lock", True)
    try:
        _prime_meta(shortcut, target)
        _prime_value(shortcut, target)
    finally:
        _set_proxy(shortcut, "proxy_sync_lock", False)
    return True


def _prime_meta(shortcut, target):
    _set_proxy(shortcut, "proxy_value_type", getattr(target, "value_type", ""))
    _set_proxy(shortcut, "proxy_index", int(getattr(target, "index", -1)))
    _set_proxy(shortcut, "proxy_array_length", int(getattr(target, "array_length", 0) or 0))
    _set_proxy(shortcut, "proxy_enum_items_json", json.dumps(list(getattr(target, "enum_items", ()) or ())))


def _prime_value(shortcut, target):
    value = _live_target_value(shortcut, target)
    return _prime_array_value(shortcut, target) if _uses_array_proxy(shortcut, target) else _prime_scalar_value(shortcut, target, value)


def _prime_scalar_value(shortcut, target, value):
    if isinstance(value, bool):
        return _set_proxy(shortcut, "proxy_bool", bool(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return _set_proxy(shortcut, "proxy_int", int(value))
    if isinstance(value, float):
        return _set_proxy(shortcut, shortcut_prop_name(shortcut, target), float(value))
    return _set_proxy(shortcut, "proxy_enum", _enum_value(shortcut, value)) if _enum_items(shortcut) else _set_proxy(shortcut, "proxy_string", str(value or ""))


def _enum_value(shortcut, value):
    items = [str(item[0]) for item in _enum_items(shortcut)]
    return str(value or "") if str(value or "") in items else (items[0] if items else "NONE")


def _enum_items(shortcut):
    return tuple(json.loads(str(getattr(shortcut, "proxy_enum_items_json", "[]")) or "[]"))


def _prime_array_value(shortcut, target):
    values = list(raw_target_value(target) or ())
    return _set_proxy(shortcut, _array_name(getattr(target, "value_type", "")), _array_fill(values, getattr(target, "value_type", ""), _vector_size(shortcut)))


def _array_name(value_type):
    names = {"BOOL": "proxy_bool_vec", "INT": "proxy_int_vec", "FLOAT": "proxy_float_vec"}
    return names.get(value_type, "proxy_float_vec")


def _array_fill(values, value_type, size):
    caster = bool if value_type == "BOOL" else int if value_type == "INT" else float
    return tuple(caster(values[index]) if index < len(values) else caster(0) for index in range(size))


def _vector_size(shortcut):
    return len(getattr(shortcut, "proxy_float_vec", ()))


def _set_proxy(shortcut, key, value):
    setattr(shortcut, key, value)
    return value


def shortcut_override_modes(context, shortcut_id, target_scp_id):
    root = root_for_context(context)
    shortcut = find_shortcut(root, shortcut_id)
    return _keep_values()[:2] if shortcut is None else override_values(shortcut, target_scp_id)[:2]


def shortcut_override_values(context, shortcut_id, target_scp_id):
    root = root_for_context(context)
    shortcut = find_shortcut(root, shortcut_id)
    return _keep_values() if shortcut is None else override_values(shortcut, target_scp_id)


def save_shortcut_override(context, shortcut_id, target_scp_id, parent_mode, child_mode, follow_rotation_mode="KEEP", rotation_strategy="KEEP"):
    root = root_for_context(context)
    shortcut = find_shortcut(root, shortcut_id)
    return bool(shortcut and upsert_override(shortcut, target_scp_id, parent_mode, child_mode, follow_rotation_mode, rotation_strategy))


def find_shortcut(root, shortcut_id):
    items = () if root is None else getattr(getattr(root, "af_shortcut_system", None), "shortcuts", ())
    return next((item for item in items if str(getattr(item, "id", "")) == str(shortcut_id or "")), None)


def _sync_context():
    try:
        from ...app.runtime_api import sync_context
    except ImportError:
        from app.runtime_api import sync_context
    return sync_context


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def live_shortcut_value(context, shortcut):
    target = resolve_shortcut_target(context, shortcut)
    return None if target is None else _live_target_value(shortcut, target)


def live_shortcut_array(context, shortcut, size, caster=float):
    target = resolve_shortcut_target(context, shortcut)
    values = [] if target is None else list(raw_target_value(target) or ())
    return tuple(caster(values[i]) if i < len(values) else caster(0) for i in range(int(size or 0)))


def live_shortcut_enum_items(context, shortcut):
    target = resolve_shortcut_target(context, shortcut)
    items = () if target is None else tuple(getattr(target, "enum_items", ()) or ())
    return items or (("NONE", "None", ""),)
