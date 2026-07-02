from ..queries.root import root_for_context

try:
    from ...core.id_utils import next_prefixed_id
    from ...core.shortcuts.owner_backsolve import init_owner_backsolve
    from ...core.shortcuts import normalize_shortcut_path, resolve_shortcut
    from ...core.shortcuts.owners import current_shortcut_owner
except ImportError:
    from core.id_utils import next_prefixed_id
    from core.shortcuts.owner_backsolve import init_owner_backsolve
    from core.shortcuts import normalize_shortcut_path, resolve_shortcut
    from core.shortcuts.owners import current_shortcut_owner


def add_shortcut_from_context(context):
    root = root_for_context(context)
    if root is None:
        return False, ""
    scene = getattr(context, "scene", None)
    checks = (_validate_name(scene), _validate_path(root, context, scene), _validate_owner(root, context))
    error = next((msg for ok, msg, _ in checks if not ok), "")
    return (False, error) if error else _create_shortcut(root, context, scene, checks)


def delete_shortcut_from_context(context, shortcut_id):
    root = root_for_context(context)
    if root is None:
        return False
    index = _shortcut_index(root.af_shortcut_system.shortcuts, shortcut_id)
    return _remove_shortcut(root.af_shortcut_system.shortcuts, index)


def _validate_name(scene):
    name = _draft_value(scene, "af_new_shortcut_name")
    return (bool(name), "Enter a shortcut name.", name)


def _validate_path(root, context, scene):
    path = normalize_shortcut_path(root, context, _draft_value(scene, "af_new_shortcut_path"))
    error = "Paste a full Blender data path that points to an object bound to the active SCP."
    return (bool(path), error, path)


def _validate_owner(root, context):
    owner_type, owner_id = current_shortcut_owner(root, context)
    return (owner_type != "NONE", "Select an SCP or VCP first.", (owner_type, owner_id))


def _create_shortcut(root, context, scene, checks):
    name, path, owner = (checks[0][2], checks[1][2], checks[2][2])
    if resolve_shortcut(root, context, path).owner is None:
        return False, "Shortcut path could not be resolved."
    _append_shortcut(root.af_shortcut_system.shortcuts, name, path, owner)
    _clear_draft(scene)
    return True, ""


def _append_shortcut(shortcuts, name, path, owner):
    item = shortcuts.add()
    item.id = next_prefixed_id(shortcuts, "SHORTCUT")
    item.name, item.data_path = name, path
    item.vector_mode = "DEFAULT"
    item.owner_type, item.owner_id = owner
    init_owner_backsolve(item, False)


def _draft_value(scene, key):
    return str(getattr(scene, key, "") or "").strip()


def _clear_draft(scene):
    scene.af_new_shortcut_name = ""
    scene.af_new_shortcut_path = ""


def _shortcut_index(shortcuts, shortcut_id):
    for index, item in enumerate(shortcuts):
        if str(getattr(item, "id", "") or "") == str(shortcut_id or ""):
            return index
    return -1


def _remove_shortcut(shortcuts, index):
    if index < 0:
        return False
    shortcuts.remove(index)
    return True
