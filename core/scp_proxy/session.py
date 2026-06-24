import json

import bpy

from .consts import COLLECTION, FLAG, NOTICE_KEY, OWNER_KEY, ROOT_KEY, SESSION_ID_KEY, SESSION_KEY, SIDE_KEY, SOURCES_KEY


def active_session(root):
    raw = "" if root is None else str(root.get(SESSION_KEY, "") or "")
    return _json_dict(raw)


def session_owner_id(root):
    return str(active_session(root).get("owner_scp_id", "") or "")


def set_session(root, payload):
    if root is not None:
        root[SESSION_KEY] = json.dumps(dict(payload or {}))


def clear_session(root):
    None if root is None else root.pop(SESSION_KEY, None)


def proxy_notice(root):
    return "" if root is None else str(root.get(NOTICE_KEY, "") or "")


def set_proxy_notice(root, text):
    if root is not None:
        root[NOTICE_KEY] = str(text or "")


def clear_proxy_notice(root):
    None if root is None else root.pop(NOTICE_KEY, None)


def ensure_proxy_collection(scene):
    col = scene.collection.children.get(COLLECTION)
    return col if col is not None else _new_collection(scene)


def proxy_object(scene, payload, side):
    name = str(dict(payload or {}).get(str(side).lower(), "") or "")
    return None if not name else bpy.data.objects.get(name)


def tag_proxy_object(obj, root, payload, side, sources):
    _set_meta(obj, ROOT_KEY, root.name)
    _set_meta(obj, FLAG, True)
    _set_meta(obj, SESSION_ID_KEY, payload["session_id"])
    _set_meta(obj, OWNER_KEY, payload["owner_scp_id"])
    _set_meta(obj, SIDE_KEY, side)
    _set_meta(obj, SOURCES_KEY, json.dumps(list(sources or ())))


def proxy_sources(obj):
    raw = "" if obj is None else str(obj.get(SOURCES_KEY, "") or "")
    return _json_list(raw)


def _new_collection(scene):
    col = bpy.data.collections.new(COLLECTION)
    scene.collection.children.link(col)
    return col


def _set_meta(obj, key, value):
    obj[str(key)] = value


def _json_dict(raw):
    data = _json_load(raw)
    return data if isinstance(data, dict) else {}


def _json_list(raw):
    data = _json_load(raw)
    return data if isinstance(data, list) else []


def _json_load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}
