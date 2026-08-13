from collections import OrderedDict
from sys import getsizeof

import bpy

_SCENE_CACHE = {}
_BOUNDED_SCENE_CACHE = {}
_GEOMETRY_GENERATIONS = {}
DEFAULT_BOUNDED_CACHE_ENTRIES = 128
DEFAULT_BOUNDED_CACHE_BYTES = 256 * 1024 * 1024


def _pointer_id(value):
    try:
        uid = int(getattr(value, "session_uid", 0) or 0)
        return uid or int(value.as_pointer())
    except Exception:
        return None


def geometry_generation(value):
    return int(_GEOMETRY_GENERATIONS.get(_pointer_id(value), 0))


def note_geometry_updates(depsgraph):
    for update in tuple(getattr(depsgraph, "updates", ()) or ()):
        if _is_geometry_update(update):
            key = _pointer_id(getattr(update, "id", None))
            _GEOMETRY_GENERATIONS[key] = _GEOMETRY_GENERATIONS.get(key, 0) + 1


def _is_geometry_update(update):
    return bool(getattr(update, "is_updated_geometry", False) or
                getattr(update, "is_updated_transform", False))


def clear_geometry_generations():
    _GEOMETRY_GENERATIONS.clear()


def _scene_bucket(scene):
    key = _pointer_id(scene)
    return None if key is None else _SCENE_CACHE.setdefault(key, {})


def scene_cache_get(scene, key):
    bucket = _scene_bucket(scene)
    return None if bucket is None else bucket.get(str(key))


def scene_cache_set(scene, key, value):
    bucket = _scene_bucket(scene)
    if bucket is not None:
        token = (_pointer_id(scene), str(key))
        _forget_bounded_token(token)
        bucket[token[1]] = value
    return value


def scene_cache_drop(scene, key):
    scene_id = _pointer_id(scene)
    bucket = None if scene_id is None else _SCENE_CACHE.get(scene_id)
    if bucket is not None:
        _drop_scene_key(scene_id, bucket, str(key))


def clear_scene_cache(scene=None, prefix=""):
    if scene is None:
        _SCENE_CACHE.clear()
        _BOUNDED_SCENE_CACHE.clear()
        return
    scene_id = _pointer_id(scene)
    bucket = None if scene_id is None else _SCENE_CACHE.get(scene_id)
    if bucket is None:
        return
    for key in tuple(bucket):
        if not prefix or str(key).startswith(str(prefix)):
            _drop_scene_key(scene_id, bucket, key)


def bounded_scene_cache_get(scene, key, namespace):
    value = scene_cache_get(scene, key)
    token = (_pointer_id(scene), str(key))
    state = _BOUNDED_SCENE_CACHE.get(str(namespace))
    if value is not None and state is not None and token in state["items"]:
        state["items"].move_to_end(token)
    return value


def bounded_scene_cache_set(scene, key, value, namespace, max_entries=DEFAULT_BOUNDED_CACHE_ENTRIES,
                            max_bytes=DEFAULT_BOUNDED_CACHE_BYTES, size_bytes=None):
    bucket = _scene_bucket(scene)
    if bucket is None:
        return value
    token = (_pointer_id(scene), str(key))
    _forget_bounded_token(token)
    bucket[token[1]] = value
    size = _bounded_size((token[1], value)) if size_bytes is None else max(0, int(size_bytes))
    _remember_bounded(namespace, token, size, max_entries, max_bytes)
    return value


def bounded_scene_cache_adopt(scene, key, namespace, max_entries=DEFAULT_BOUNDED_CACHE_ENTRIES,
                              max_bytes=DEFAULT_BOUNDED_CACHE_BYTES, size_bytes=None):
    value = scene_cache_get(scene, key)
    if value is None:
        return None
    return bounded_scene_cache_set(scene, key, value, namespace, max_entries, max_bytes, size_bytes)


def bounded_scene_cache_stats(namespace=""):
    if namespace:
        return _bounded_state_stats(_BOUNDED_SCENE_CACHE.get(str(namespace)))
    states = tuple(_BOUNDED_SCENE_CACHE.values())
    return {"entries": sum(len(s["items"]) for s in states),
            "bytes": sum(s["bytes"] for s in states), "namespaces": len(states)}


def _bounded_state(namespace, max_entries, max_bytes):
    state = _BOUNDED_SCENE_CACHE.setdefault(str(namespace), {
        "items": OrderedDict(), "bytes": 0, "max_entries": 0, "max_bytes": 0})
    state["max_entries"] = max(1, int(max_entries))
    state["max_bytes"] = max(1, int(max_bytes))
    return state


def _remember_bounded(namespace, token, size, max_entries, max_bytes):
    state = _bounded_state(namespace, max_entries, max_bytes)
    state["items"][token] = max(0, int(size))
    state["bytes"] += state["items"][token]
    _prune_bounded(state)


def _prune_bounded(state):
    too_many = lambda: len(state["items"]) > state["max_entries"]
    too_large = lambda: state["bytes"] > state["max_bytes"]
    while state["items"] and (too_many() or too_large()):
        token, size = state["items"].popitem(last=False)
        state["bytes"] -= size
        bucket = _SCENE_CACHE.get(token[0])
        if bucket is not None:
            bucket.pop(token[1], None)


def _forget_bounded_token(token):
    for state in _BOUNDED_SCENE_CACHE.values():
        size = state["items"].pop(token, None)
        if size is not None:
            state["bytes"] -= size


def _drop_scene_key(scene_id, bucket, key):
    _forget_bounded_token((scene_id, str(key)))
    bucket.pop(str(key), None)


def _bounded_size(value, seen=None):
    seen = set() if seen is None else seen
    marker = id(value)
    if marker in seen:
        return 0
    seen.add(marker)
    size = max(getsizeof(value, 0), int(getattr(value, "nbytes", 0) or 0))
    if isinstance(value, dict):
        size += sum(_bounded_size(k, seen) + _bounded_size(v, seen) for k, v in value.items())
    elif isinstance(value, (tuple, list, set, frozenset, OrderedDict)):
        size += sum(_bounded_size(item, seen) for item in value)
    return size


def _bounded_state_stats(state):
    if state is None:
        return {"entries": 0, "bytes": 0, "max_entries": 0, "max_bytes": 0}
    return {"entries": len(state["items"]), "bytes": state["bytes"],
            "max_entries": state["max_entries"], "max_bytes": state["max_bytes"]}


def _scene_has_obj(scene, obj):
    try:
        objs = getattr(scene, "objects", None)
        if hasattr(objs, "get"):
            return objs.get(getattr(obj, "name", "")) == obj
        return obj in tuple(objs or ())
    except Exception:
        return False


def _valid_root(scene, obj):
    try:
        return bool(scene and obj and obj.get("anthroforge_root") and _scene_has_obj(scene, obj))
    except Exception:
        return False


def get_af_root(scene=None):
    if scene is None:
        return None
    root = scene_cache_get(scene, "af_root")
    if _valid_root(scene, root):
        return root
    root = next((obj for obj in scene.objects if obj.get("anthroforge_root")), None)
    return scene_cache_set(scene, "af_root", root)


def scene_for_id(owner):
    scenes = tuple(getattr(owner, "users_scene", ()) or ())
    return scenes[0] if scenes else None


def view_layer_for_scene(scene):
    layers = tuple(getattr(scene, "view_layers", ()) or ())
    return None if scene is None or not layers else layers[0]


def depsgraph_for_scene(scene):
    layer = view_layer_for_scene(scene)
    update_scene_view_layer(scene)
    return None if layer is None else getattr(layer, "depsgraph", None)


def update_scene_view_layer(scene):
    try:
        None if scene is None else view_layer_for_scene(scene).update()
    except Exception:
        return


def create_af_root(scene):
    root = bpy.data.objects.new("AF_ROOT", None)
    scene.collection.objects.link(root)
    root.empty_display_type, root.empty_display_size = "PLAIN_AXES", 0.5
    root["anthroforge_root"] = True
    root.af_scp_system, root.af_vcp_system, root.af_shortcut_system
    return scene_cache_set(scene, "af_root", root)


def ensure_af_root(scene):
    return get_af_root(scene) or create_af_root(scene)
