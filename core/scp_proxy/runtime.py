import bpy
from bpy.app.handlers import persistent

from ..utils import get_af_root
from .scope import proxy_scope
from .session import active_session, set_proxy_notice
from .signature import snapshot_key, snapshot_row
from .visibility import deactivate_session

_PENDING = {}
_TIMER_ARMED = False


def run_proxy_session_guard(scene, depsgraph=None, force=False):
    root = get_af_root(scene)
    return False if root is None else _guard_root(scene, root, depsgraph, bool(force))


def _guard_root(scene, root, depsgraph, force):
    session = active_session(root)
    reason = "" if not session else _invalid_reason(scene, root, session, depsgraph, force)
    return False if not reason else _queue_exit(scene, root, reason)


def _invalid_reason(scene, root, session, depsgraph, force):
    if _stale_proxy(session):
        return "Proxy view exited: session became stale."
    if not force and not _has_relevant_update(root, session, depsgraph):
        return ""
    return _scope_reason(root, session) or _signature_reason(scene, root, session, depsgraph)


def _stale_proxy(session):
    names = [str(session.get(key, "") or "") for key in ("original", "mirrored")]
    return any(name and bpy.data.objects.get(name) is None for name in names)


def _has_relevant_update(root, session, depsgraph):
    if depsgraph is None:
        return True
    names = _watch_names(root, session)
    return any(_relevant_owner(root, names, getattr(update, "id", None)) for update in depsgraph.updates)


def _watch_names(root, session):
    rows = _session_rows(session)
    return {root.name} | {str(row.get("object_name", "") or "") for row in rows} | {str(row.get("mesh_name", "") or "") for row in rows}


def _relevant_owner(root, names, owner):
    if owner is None:
        return False
    if str(getattr(owner, "name", "") or "") in names:
        return True
    return isinstance(owner, bpy.types.Object) and owner.get("af_root_name") == root.name


def _scope_reason(root, session):
    owner_id = str(session.get("owner_scp_id", "") or "")
    scope = proxy_scope(root, owner_id)
    if scope.owner_id != owner_id or tuple(scope.scp_ids) != tuple(session.get("scp_ids", ())):
        return "Proxy view exited: SCP scope changed."
    if tuple(scope.mirror_ids) != tuple(session.get("mirror_target_ids", ())):
        return "Proxy view exited: mirror scope changed."
    return "" if _scope_keys(scope) == _session_keys(session) else "Proxy view exited: proxy sources changed."


def _scope_keys(scope):
    return [snapshot_key(item) for item in scope.contributors]


def _session_keys(session):
    return [(str(row.get("scp_id", "")), str(row.get("object_name", "")), str(row.get("mesh_name", ""))) for row in _session_rows(session)]


def _signature_reason(scene, root, session, depsgraph):
    try:
        current = _current_rows(scene, root, session, depsgraph)
    except RuntimeError:
        return "Proxy view exited: source topology changed."
    wanted = {str(row.get("scp_id", "")): str(row.get("signature", "") or "") for row in _session_rows(session)}
    have = {str(row.get("scp_id", "")): str(row.get("signature", "") or "") for row in current}
    return "" if wanted == have else "Proxy view exited: source topology changed."


def _current_rows(scene, root, session, depsgraph):
    scope = proxy_scope(root, str(session.get("owner_scp_id", "") or ""))
    return [snapshot_row(scene, item, depsgraph=depsgraph, refresh=depsgraph is None) for item in scope.contributors]


def _session_rows(session):
    rows = session.get("source_snapshots", ()) if isinstance(session, dict) else ()
    return list(rows or ())


def _queue_exit(scene, root, reason):
    _PENDING[(scene.name, root.name)] = str(reason or "Proxy view exited.")
    _arm_timer()
    return True


def _arm_timer():
    global _TIMER_ARMED
    if _TIMER_ARMED:
        return
    _TIMER_ARMED = True
    bpy.app.timers.register(_flush_pending, first_interval=0.0)


def _flush_pending():
    global _TIMER_ARMED
    item = next(iter(_PENDING.items()), None)
    if item is None:
        _TIMER_ARMED = False
        return None
    if not _exit_now(*item):
        return 0.1
    _PENDING.pop(item[0], None)
    return 0.0


def _exit_now(key, reason):
    scene = bpy.data.scenes.get(key[0])
    root = bpy.data.objects.get(key[1])
    if scene is None or root is None or not active_session(root):
        return True
    if not _ensure_object_mode():
        return False
    set_proxy_notice(root, reason)
    deactivate_session(root, scene)
    return True


def _ensure_object_mode():
    if getattr(bpy.context, "mode", "") == "OBJECT":
        return True
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
        return True
    except Exception:
        return False


def flush_proxy_session_runtime():
    while _PENDING:
        if _flush_pending() not in (0.0, None):
            break


@persistent
def _on_load_post(_dummy):
    global _TIMER_ARMED
    _PENDING.clear()
    _TIMER_ARMED = False


def register_proxy_session_runtime():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    if run_proxy_session_guard not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(run_proxy_session_guard)


def unregister_proxy_session_runtime():
    global _TIMER_ARMED
    _PENDING.clear()
    _TIMER_ARMED = False
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if run_proxy_session_guard in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(run_proxy_session_guard)
