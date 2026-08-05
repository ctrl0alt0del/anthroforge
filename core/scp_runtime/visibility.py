from dataclasses import dataclass, field


_SESSIONS = {}


@dataclass
class SCPVisibilitySession:
    scene: object
    view_layer: object
    root_name: str
    scp_id: str
    states: dict = field(default_factory=dict)


def toggle_scp_isolation(scene, view_layer, root, scp_id):
    key = _session_key(scene, view_layer)
    session = _SESSIONS.get(key)
    root_name, target = str(getattr(root, "name", "") or ""), str(scp_id or "")
    if session is not None and session.root_name == root_name and session.scp_id == target:
        restore_scp_isolation(scene, view_layer)
        return False
    session = _switch_or_create(session, scene, view_layer, root_name, target)
    _SESSIONS[key] = session
    _apply_session(session)
    return True


def _switch_or_create(session, scene, view_layer, root_name, scp_id):
    if session is not None and session.root_name == root_name:
        session.scp_id = scp_id
        return session
    _restore_session(session) if session is not None else None
    return SCPVisibilitySession(scene, view_layer, root_name, scp_id)


def isolated_scp_id(scene, view_layer, root_name=""):
    session = _SESSIONS.get(_session_key(scene, view_layer))
    if session is None or (root_name and session.root_name != str(root_name)):
        return ""
    return session.scp_id


def restore_scp_isolation(scene, view_layer):
    session = _SESSIONS.pop(_session_key(scene, view_layer), None)
    _restore_session(session)
    return session is not None


def reapply_scp_isolations(scene):
    for session in tuple(_SESSIONS.values()):
        if _pointer(session.scene) == _pointer(scene):
            _apply_session(session)


def restore_all_scp_isolations():
    for session in tuple(_SESSIONS.values()):
        _restore_session(session)
    _SESSIONS.clear()


def _apply_session(session):
    for obj, owner_id in _owned_objects(session.scene, session.root_name):
        key = _pointer(obj)
        if key not in session.states:
            session.states[key] = (obj, _hidden(obj, session.view_layer))
        original = session.states[key][1]
        _set_hidden(obj, original if owner_id == session.scp_id else True, session.view_layer)


def _restore_session(session):
    if session is None:
        return
    for obj, hidden in tuple(session.states.values()):
        _set_hidden(obj, hidden, session.view_layer)


def _owned_objects(scene, root_name):
    for obj in tuple(getattr(scene, "objects", ()) or ()):
        owner_id = _object_scp_id(obj, root_name)
        if owner_id:
            yield obj, owner_id


def _object_scp_id(obj, root_name):
    if str(obj.get("af_root_name", "") or "") != str(root_name):
        return ""
    if obj.get("af_scp_mirror"):
        return str(obj.get("af_source_scp_id", "") or "")
    return str(obj.get("af_scp_id", "") or "")


def _hidden(obj, view_layer):
    try:
        return bool(obj.hide_get(view_layer=view_layer))
    except (ReferenceError, RuntimeError, TypeError):
        return False


def _set_hidden(obj, hidden, view_layer):
    try:
        obj.hide_set(bool(hidden), view_layer=view_layer)
    except (ReferenceError, RuntimeError, TypeError):
        pass


def _session_key(scene, view_layer):
    return _pointer(scene), _pointer(view_layer)


def _pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)
