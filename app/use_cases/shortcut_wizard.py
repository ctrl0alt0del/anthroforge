from ..queries.root import root_for_context

try:
    from ...core.id_utils import next_prefixed_id
    from ...core.shortcuts import canonical_shortcut_path, normalize_shortcut_path
    from ...core.shortcuts.owner_backsolve import init_owner_backsolve
    from ...core.shortcuts.owners import current_shortcut_owner, matches_shortcut_owner
    from ...core.scp_runtime.common import find_scp_by_id
    from ...core.shortcuts.wizard_scan import collect_shortcut_fields
except ImportError:
    from core.id_utils import next_prefixed_id
    from core.shortcuts import canonical_shortcut_path, normalize_shortcut_path
    from core.shortcuts.owner_backsolve import init_owner_backsolve
    from core.shortcuts.owners import current_shortcut_owner, matches_shortcut_owner
    from core.scp_runtime.common import find_scp_by_id
    from core.shortcuts.wizard_scan import collect_shortcut_fields


def populate_shortcut_wizard(context):
    root, owner, obj, scene = _wizard_context(context)
    if root is None or owner[0] == "NONE" or obj is None:
        return False, _wizard_error(root, owner, obj)
    fields = tuple(collect_shortcut_fields(obj))
    if not fields:
        return False, "No numeric shortcut candidates were found on the active object."
    _reset_wizard(scene)
    _set_wizard_wildcard(scene, root, owner)
    _append_wizard_items(scene.af_shortcut_wizard_items, _wizard_rows(root, context, owner, fields))
    return True, ""


def apply_shortcut_wizard(context):
    root, owner, _obj, scene = _wizard_context(context)
    if root is None or owner[0] == "NONE":
        return False, _wizard_error(root, owner, object())
    error = _apply_wizard_items(root.af_shortcut_system.shortcuts, scene.af_shortcut_wizard_items, owner, _wizard_wildcard(scene))
    if error:
        return False, error
    clear_shortcut_wizard(scene)
    return True, ""


def clear_shortcut_wizard(scene):
    _reset_wizard(scene)


def _wizard_context(context):
    root = root_for_context(context)
    owner = ("NONE", "") if root is None else current_shortcut_owner(root, context)
    return root, owner, getattr(context, "active_object", None), getattr(context, "scene", None)


def _wizard_error(root, owner, obj):
    if root is None:
        return ""
    if owner[0] == "NONE":
        return "Select an SCP or VCP first."
    return "Select an active object first." if obj is None else ""


def _wizard_rows(root, context, owner, fields):
    existing = _existing_shortcuts(root, owner)
    return tuple(_wizard_row(root, context, existing, field) for field in fields)


def _existing_shortcuts(root, owner):
    rows = [item for item in tuple(root.af_shortcut_system.shortcuts) if matches_shortcut_owner(item, *owner)]
    return {_shortcut_key(getattr(item, "data_path", ""), getattr(item, "vector_mode", "DEFAULT")): item for item in rows}


def _wizard_row(root, context, existing, field):
    path = normalize_shortcut_path(root, context, field.data_path)
    mode = str(getattr(field, "vector_mode", "DEFAULT") or "DEFAULT")
    match = existing.get(_shortcut_key(path, mode))
    return {"label": field.label, "data_path": path, "shortcut_id": _shortcut_id(match), "shortcut_name": field.default_name if match is None else match.name, "enabled": match is not None, "vector_mode": mode}


def _shortcut_key(path, vector_mode):
    return canonical_shortcut_path(path), str(vector_mode or "DEFAULT").upper()


def _shortcut_id(shortcut):
    return "" if shortcut is None else str(getattr(shortcut, "id", "") or "")


def _append_wizard_items(items, rows):
    for row in tuple(rows or ()):
        _append_wizard_item(items, row)


def _append_wizard_item(items, row):
    item = items.add()
    for key, value in dict(row or {}).items():
        setattr(item, key, value)


def _reset_wizard(scene):
    if scene is None:
        return
    scene.af_shortcut_wizard_active_index = -1
    scene.af_shortcut_wizard_wildcard_value = ""
    while len(scene.af_shortcut_wizard_items):
        scene.af_shortcut_wizard_items.remove(len(scene.af_shortcut_wizard_items) - 1)


def _wizard_wildcard(scene):
    return str(getattr(scene, "af_shortcut_wizard_wildcard_value", "") or "")


def _set_wizard_wildcard(scene, root, owner):
    if scene is not None:
        scene.af_shortcut_wizard_wildcard_value = _default_wildcard(root, owner)


def _default_wildcard(root, owner):
    return _scp_name(root, owner[1]) if owner[0] == "SCP" else ""


def _scp_name(root, scp_id):
    scp = find_scp_by_id(root, scp_id)
    return str(getattr(scp, "name", "") or "")


def _apply_wizard_items(shortcuts, items, owner, wildcard):
    for item in tuple(items or ()):
        error = _apply_wizard_item(shortcuts, item, owner, wildcard)
        if error:
            return error
    return ""


def _apply_wizard_item(shortcuts, item, owner, wildcard):
    if bool(getattr(item, "enabled", False)):
        return _upsert_wizard_shortcut(shortcuts, item, owner, wildcard)
    _delete_shortcut(shortcuts, getattr(item, "shortcut_id", ""))
    return ""


def _upsert_wizard_shortcut(shortcuts, item, owner, wildcard):
    name = _resolved_name(item, wildcard)
    if not name:
        return f"Shortcut name is required for {getattr(item, 'label', 'selected row')}."
    shortcut = _find_shortcut(shortcuts, getattr(item, "shortcut_id", ""))
    return _create_shortcut(shortcuts, item, owner, name) if shortcut is None else _update_shortcut(shortcut, item, owner, name)


def _resolved_name(item, wildcard):
    return _expanded_name(_raw_name(item), wildcard).strip()


def _raw_name(item):
    return str(getattr(item, "shortcut_name", "") or "")


def _expanded_name(name, wildcard):
    return str(name or "").replace("*", str(wildcard or ""))


def _create_shortcut(shortcuts, item, owner, name):
    shortcut = shortcuts.add()
    shortcut.id = next_prefixed_id(shortcuts, "SHORTCUT")
    init_owner_backsolve(shortcut, False)
    _write_shortcut(shortcut, item, owner, name)
    return ""


def _update_shortcut(shortcut, item, owner, name):
    _write_shortcut(shortcut, item, owner, name)
    return ""


def _write_shortcut(shortcut, item, owner, name):
    shortcut.name = name
    shortcut.data_path = str(getattr(item, "data_path", "") or "")
    shortcut.vector_mode = str(getattr(item, "vector_mode", "DEFAULT") or "DEFAULT")
    shortcut.owner_type, shortcut.owner_id = owner


def _find_shortcut(shortcuts, shortcut_id):
    return next((item for item in tuple(shortcuts or ()) if _shortcut_id(item) == str(shortcut_id or "")), None)


def _delete_shortcut(shortcuts, shortcut_id):
    index = _shortcut_index(shortcuts, shortcut_id)
    shortcuts.remove(index) if index >= 0 else None


def _shortcut_index(shortcuts, shortcut_id):
    for index, item in enumerate(tuple(shortcuts or ())):
        if _shortcut_id(item) == str(shortcut_id or ""):
            return index
    return -1
