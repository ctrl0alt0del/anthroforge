from ..visualization.mirror_objects import remove_obj
from .session import active_session, clear_session, proxy_object, set_session


def activate_session(root, scene, payload, hidden_names):
    data = dict(payload or {})
    data["hidden_object_names"] = list(hidden_names or ())
    _hide_objects(scene, hidden_names)
    set_session(root, data)


def deactivate_session(root, scene):
    payload = active_session(root)
    _show_objects(scene, payload.get("hidden_object_names", ()))
    _remove_proxy(scene, payload, "original")
    _remove_proxy(scene, payload, "mirrored")
    clear_session(root)


def hidden_scope_objects(scene, root_name, scp_ids, mirror_ids):
    live = tuple(_scope_objects(scene, root_name, scp_ids, mirror_ids))
    return [obj.name for obj in live if not obj.hide_get()]


def _scope_objects(scene, root_name, scp_ids, mirror_ids):
    for obj in scene.objects:
        if _is_scope_bound(obj, root_name, scp_ids) or _is_scope_mirror(obj, root_name, mirror_ids):
            yield obj


def _is_scope_bound(obj, root_name, scp_ids):
    valid = obj.get("af_root_name") == root_name and obj.get("af_scp_bound") and not obj.get("af_scp_mirror")
    return bool(valid and str(obj.get("af_scp_id") or "") in set(scp_ids or ()))


def _is_scope_mirror(obj, root_name, mirror_ids):
    valid = obj.get("af_root_name") == root_name and obj.get("af_scp_mirror")
    return bool(valid and str(obj.get("af_source_scp_id") or "") in set(mirror_ids or ()))


def _hide_objects(scene, names):
    for obj in _named_objects(scene, names):
        obj.hide_set(True)


def _show_objects(scene, names):
    for obj in _named_objects(scene, names):
        obj.hide_set(False)


def _named_objects(scene, names):
    for name in tuple(names or ()):
        obj = scene.objects.get(str(name)) if hasattr(scene.objects, "get") else None
        if obj is not None:
            yield obj


def _remove_proxy(scene, payload, side):
    obj = proxy_object(scene, payload, side)
    None if obj is None else remove_obj(obj)
