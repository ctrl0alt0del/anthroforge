import json

from ..queries.root import root_for_context

try:
    from ...core.shortcuts import override_values, raw_target_value, resolve_shortcut, target_value, upsert_override, write_target_value
    from ...core.shortcuts.owner_backsolve import capture_owner_backsolve_snapshot
    from ...core.shortcuts.proxy_props import shortcut_prop_name
    from ...core.shortcuts.vector_modes import is_uniform_vector_shortcut
    from ...core.shortcuts.owners import shortcut_relation
    from ...core.shortcuts.session_state import begin_override_sessions, cached_override_runtime, clear_override_session, store_override_runtime, suppress_next_depsgraph_ids
    from ...core.scp_runtime.common import find_scp_by_id
    from ...core.scp_runtime.runtime_state import restore_attachment_runtime, snapshot_attachment_runtime
except ImportError:
    from core.shortcuts import override_values, raw_target_value, resolve_shortcut, target_value, upsert_override, write_target_value
    from core.shortcuts.owner_backsolve import capture_owner_backsolve_snapshot
    from core.shortcuts.proxy_props import shortcut_prop_name
    from core.shortcuts.vector_modes import is_uniform_vector_shortcut
    from core.shortcuts.owners import shortcut_relation
    from core.shortcuts.session_state import begin_override_sessions, cached_override_runtime, clear_override_session, store_override_runtime, suppress_next_depsgraph_ids
    from core.scp_runtime.common import find_scp_by_id
    from core.scp_runtime.runtime_state import restore_attachment_runtime, snapshot_attachment_runtime


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


def set_shortcut_value(context, shortcut, value):
    return apply_shortcut_value(context, shortcut, value)


def flush_pending_shortcut_values():
    return None


def unregister_shortcut_queue():
    return None


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
    scene = getattr(context, "scene", None)
    overrides = _session_overrides(root, shortcut)
    plan = _session_plan(root, shortcut, overrides)
    authored = _authored_runtime(root, plan)
    session = _session_state(root, scene, shortcut, overrides, plan)
    return _run_scp_session(context, root, shortcut, target, value, plan, session, authored)


def _session_state(root, scene, shortcut, overrides, plan):
    owner = _owner_backsolve_snapshot(root, scene, shortcut)
    _prime_session_runtime(root, plan)
    begin_override_sessions(overrides)
    runtime = _prepare_session_runtime(root, scene, plan)
    suppressed = _suppressed_ids(root, shortcut, overrides)
    suppress_next_depsgraph_ids(suppressed)
    return {"owner": owner, "runtime": runtime, "suppressed": suppressed}


def _owner_backsolve_snapshot(root, scene, shortcut):
    if not _owner_backsolve_enabled(shortcut):
        return None
    return capture_owner_backsolve_snapshot(root, scene, _owner_id(shortcut))


def _owner_backsolve_enabled(shortcut):
    return bool(getattr(shortcut, "owner_backsolve", True))


def _run_scp_session(context, root, shortcut, target, value, plan, session, authored):
    try:
        _run_shortcut_passes(context, root, shortcut, target, value, plan, session)
        _store_session_runtime(shortcut, plan, session.get("runtime", {}))
        return True
    finally:
        clear_override_session()
        _restore_authored_runtime(root, authored)


def _run_shortcut_passes(context, root, shortcut, target, value, plan, session):
    write_target_value(target, value)
    _run_shortcut_sync(context, _session_request(shortcut, plan, session))


def _session_overrides(root, shortcut):
    ids = _override_target_ids(root, shortcut)
    return {sid: values for sid in ids for values in (_normalized_values(root, shortcut, sid),) if _has_override_values(values)}


def _override_target_ids(root, shortcut):
    items = getattr(shortcut, "overrides", ())
    return [sid for sid in (_entry_target_id(item) for item in items) if _valid_override_target(root, shortcut, sid)]


def _entry_target_id(item):
    return str(getattr(item, "target_scp_id", "") or "")


def _valid_override_target(root, shortcut, scp_id):
    return find_scp_by_id(root, scp_id) is not None and shortcut_relation(root, shortcut, scp_id) == "ANCESTOR"


def _normalized_values(root, shortcut, scp_id):
    return _normalized_override_values(find_scp_by_id(root, scp_id), override_values(shortcut, scp_id))


def _normalized_override_values(scp, values):
    authored, data = _authored_values(scp), tuple(values or ())
    return tuple(_normalized_value(authored, data, index) for index in range(4))


def _normalized_value(authored, values, index):
    value = str(values[index] if index < len(values) else "KEEP")
    return "KEEP" if value == str(authored[index]) else value


def _authored_values(scp):
    return (_authored_parent(scp), _authored_child(scp), _authored_follow(scp), _authored_strategy(scp))


def _authored_parent(scp):
    return str(getattr(scp, "attach_parent_anchor_mode", "SURFACE_NEAREST") or "SURFACE_NEAREST").upper()


def _authored_child(scp):
    return str(getattr(scp, "attach_child_anchor_mode", "FACE_CENTER") or "FACE_CENTER").upper()


def _authored_follow(scp):
    return "ENABLED" if bool(getattr(scp, "attach_follow_rotation", True)) else "DISABLED"


def _authored_strategy(scp):
    return str(getattr(scp, "attach_tangent_strategy", "AUTO") or "AUTO").upper()


def _has_override_values(values):
    return any(str(value or "KEEP") != "KEEP" for value in tuple(values or ()))


def _session_plan(root, shortcut, overrides):
    runtime = _runtime_overrides(overrides)
    cached = cached_override_runtime(_cache_key(shortcut), runtime)
    return {"runtime_overrides": runtime, "cached_runtime": cached, "fresh_ids": _fresh_ids(root, runtime, cached)}


def _runtime_overrides(overrides):
    items = dict(overrides or {}).items()
    return {sid: values for sid, values in items if _needs_session_recapture(values)}


def _fresh_ids(root, runtime_overrides, cached_runtime):
    items = dict(runtime_overrides or {}).items()
    return {sid for sid, values in items if sid not in cached_runtime and _needs_recapture(root, sid, values)}


def _session_request(shortcut, plan, session):
    owner_id = _owner_id(shortcut)
    return _sync_request(owner_id, _session_dirty_ids(shortcut, plan), {owner_id}, session.get("owner"))


def _sync_request(owner_id, dirty_ids, target_ids, owner=None):
    payload = _session_payload(owner_id, target_ids, owner)
    return set(dirty_ids or set()), payload


def _session_payload(owner_id, target_ids, owner=None):
    targets = [sid for sid in sorted(set(target_ids or set())) if sid]
    payload = {"scp_apply_target_ids": targets, "scp_apply_parent_ids": [owner_id] if owner_id else [], "scp_recapture_ids": []}
    payload["scp_owner_backsolve"] = dict(owner) if owner else {}
    return payload


def _session_dirty_ids(shortcut, plan):
    owner_id = _owner_id(shortcut)
    fresh = set(plan.get("fresh_ids", set()) or set())
    return {sid for sid in ({owner_id} | fresh) if sid}


def _recapture_ids(root, overrides):
    items = dict(overrides or {}).items()
    return {sid for sid, values in items if _needs_recapture(root, sid, values)}


def _needs_recapture(root, scp_id, values):
    scp = find_scp_by_id(root, scp_id)
    return _needs_session_recapture(values) and bool(str(getattr(scp, "parent_id", "") or ""))


def _authored_runtime(root, plan):
    return {sid: snapshot_attachment_runtime(scp) for sid in _runtime_ids(plan) for scp in (_runtime_scp(root, sid),) if scp is not None}


def _runtime_ids(plan):
    return tuple(dict(plan.get("runtime_overrides", {}) or {}).keys())


def _runtime_scp(root, sid):
    return find_scp_by_id(root, sid)


def _prime_session_runtime(root, plan):
    for sid, snapshot in dict(plan.get("cached_runtime", {}) or {}).items():
        _restore_runtime_snapshot(root, sid, snapshot)


def _prepare_session_runtime(root, scene, plan):
    _capture_session_runtime(root, scene, plan)
    return _session_runtime(root, plan)


def _capture_session_runtime(root, scene, plan):
    if scene is None:
        return
    for sid in set(plan.get("fresh_ids", set()) or set()):
        _recapture_attachment(root, scene, sid)


def _session_runtime(root, plan):
    return {sid: snapshot_attachment_runtime(scp) for sid in _runtime_ids(plan) for scp in (_runtime_scp(root, sid),) if scp is not None}


def _store_session_runtime(shortcut, plan, runtime):
    store_override_runtime(_cache_key(shortcut), plan.get("runtime_overrides", {}), runtime)


def _cache_key(shortcut):
    pointer = getattr(shortcut, "as_pointer", None)
    return str(pointer()) if callable(pointer) else str(getattr(shortcut, "id", "") or "")


def _recapture_attachment(root, scene, sid):
    try:
        from ...core.scp_runtime.attachment_runtime import recapture_attachment_for_scp
    except ImportError:
        from core.scp_runtime.attachment_runtime import recapture_attachment_for_scp
    recapture_attachment_for_scp(root, scene, sid)


def _restore_authored_runtime(root, authored):
    for sid, snapshot in dict(authored or {}).items():
        _restore_runtime_snapshot(root, sid, snapshot)


def _restore_runtime_snapshot(root, sid, snapshot):
    scp = _runtime_scp(root, sid)
    restore_attachment_runtime(scp, snapshot) if scp is not None else None


def _owner_id(shortcut):
    return str(getattr(shortcut, "owner_id", "") or "")


def _suppressed_ids(root, shortcut, overrides):
    owner_id = _owner_id(shortcut)
    ids = _owner_subtree_ids(root, owner_id) or ({owner_id} | set(dict(overrides or {}).keys()))
    return {sid for sid in ids if sid}


def _owner_subtree_ids(root, owner_id):
    system = getattr(root, "af_scp_system", None)
    scps = () if system is None else getattr(system, "scps", ())
    scp_by_id = {str(getattr(scp, "id", "") or ""): scp for scp in scps}
    return set() if owner_id not in scp_by_id else _descendant_ids(_children_map()(scp_by_id), owner_id)


def _descendant_ids(kids, owner_id):
    out, stack = set(), [owner_id]
    while stack:
        sid = stack.pop()
        if sid and sid not in out:
            out.add(sid)
            stack.extend(reversed(kids.get(sid, ())))
    return out


def _run_shortcut_sync(context, request):
    dirty_ids, payload = request
    _sync_context()(context, dirty_hints=_dirty_hints_for()("SCP", dirty_ids), source="shortcut", event_type="UPDATE", payload=payload)


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
    values = _keep_values() if shortcut is None else override_values(shortcut, target_scp_id)
    return (*values, _owner_backsolve_enabled(shortcut))


def save_shortcut_override(context, shortcut_id, target_scp_id, owner_backsolve, parent_mode, child_mode, follow_rotation_mode="KEEP", rotation_strategy="KEEP"):
    root = root_for_context(context)
    shortcut = find_shortcut(root, shortcut_id)
    if shortcut is None:
        return False
    shortcut.owner_backsolve = bool(owner_backsolve)
    if not can_edit_shortcut_override(context, shortcut_id, target_scp_id):
        return True
    upsert_override(shortcut, target_scp_id, parent_mode, child_mode, follow_rotation_mode, rotation_strategy)
    return True


def can_edit_shortcut_override(context, shortcut_id, target_scp_id):
    root = root_for_context(context)
    shortcut = find_shortcut(root, shortcut_id)
    return _can_edit_override(root, shortcut, target_scp_id)


def _can_edit_override(root, shortcut, target_scp_id):
    if shortcut is None or find_scp_by_id(root, target_scp_id) is None:
        return False
    return shortcut_relation(root, shortcut, target_scp_id) == "ANCESTOR"


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


def _children_map():
    try:
        from ...core.scp_runtime.tree import children_map
    except ImportError:
        from core.scp_runtime.tree import children_map
    return children_map


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
