import bpy

_SCENE_CACHE = {}


def _pointer_id(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return None


def _scene_bucket(scene):
    key = _pointer_id(scene)
    return None if key is None else _SCENE_CACHE.setdefault(key, {})


def scene_cache_get(scene, key):
    bucket = _scene_bucket(scene)
    return None if bucket is None else bucket.get(str(key))


def scene_cache_set(scene, key, value):
    bucket = _scene_bucket(scene)
    if bucket is not None:
        bucket[str(key)] = value
    return value


def scene_cache_drop(scene, key):
    bucket = _scene_bucket(scene)
    if bucket is not None:
        bucket.pop(str(key), None)


def clear_scene_cache(scene=None, prefix=""):
    if scene is None:
        _SCENE_CACHE.clear()
        return
    bucket = _scene_bucket(scene)
    if bucket is None:
        return
    for key in tuple(bucket):
        if not prefix or str(key).startswith(str(prefix)):
            bucket.pop(key, None)


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
