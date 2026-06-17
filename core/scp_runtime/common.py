from mathutils import Vector

from ..utils import scene_cache_drop, scene_cache_get, scene_cache_set, scene_for_id

_EPS = 1.0e-6
_APPLIED_MW_KEY = "af_scp_attach_applied_mw"


def as_id(value):
    return str(value or "")


def as_axis(value):
    axis = str(value or "X").upper()
    return axis if axis in {"X", "Y", "Z"} else "X"


def as_bool(value, default=False):
    return bool(default) if value is None else bool(value)


def as_vec3(value, default):
    try:
        return Vector((float(value[0]), float(value[1]), float(value[2])))
    except Exception:
        return Vector(default)


def set_prop_raw(prop, key, value):
    try:
        setattr(prop, key, value)
    except Exception:
        try:
            prop[key] = value
        except Exception:
            pass


def vec3_close(a, b, eps=1.0e-7):
    return (as_vec3(a, (0.0, 0.0, 0.0)) - as_vec3(b, (0.0, 0.0, 0.0))).length <= float(eps)


def matrix_flat16(matrix):
    return [float(cell) for row in matrix for cell in row]


def is_matrix_close(a, b, eps=_EPS):
    valid = isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))
    valid = valid and len(a) == 16 and len(b) == 16
    return valid and all(abs(float(av) - float(bv)) <= float(eps) for av, bv in zip(a, b))


def mark_applied_matrix(obj):
    try:
        obj[_APPLIED_MW_KEY] = matrix_flat16(obj.matrix_world)
    except Exception:
        pass


def is_runtime_applied_matrix(obj, eps=_EPS):
    raw = obj.get(_APPLIED_MW_KEY)
    return is_matrix_close(raw, matrix_flat16(obj.matrix_world), eps=eps)


def is_bound_scp_obj(obj, root_name):
    valid = obj and not obj.get("af_scp_mirror") and obj.get("af_root_name") == root_name
    return bool(valid and obj.get("af_scp_bound") and obj.get("af_scp_id"))


def is_transform_scp_obj(obj, root_name):
    return bool(is_bound_scp_obj(obj, root_name) and obj.get("af_scp_transform"))


def is_geometry_scp_obj(obj, root_name):
    return bool(is_bound_scp_obj(obj, root_name) and obj.get("af_scp_geometry"))


def iter_bound_scp_objects(scene, root_name):
    for obj in scene.objects:
        if is_bound_scp_obj(obj, root_name):
            yield obj


def is_geometry_mesh_scp_obj(obj, root_name):
    return bool(is_geometry_scp_obj(obj, root_name) and obj.type == "MESH")


def iter_geometry_mesh_scp_objects(scene, root_name):
    for obj in scene.objects:
        if is_geometry_mesh_scp_obj(obj, root_name):
            yield obj


def _index_key(root_name):
    return f"scp_index:{as_id(root_name)}"


def _prop_key(root):
    return f"scp_props:{_root_id(root)}"


def _root_id(root):
    try:
        return int(root.as_pointer())
    except Exception:
        return id(root)


def _scp_ids(root):
    return tuple(as_id(s.id) for s in getattr(getattr(root, "af_scp_system", None), "scps", ()))


def invalidate_scp_object_maps(scene, root_name):
    scene_cache_drop(scene, _index_key(root_name))


def _cached_index_ok(cached, count):
    return bool(cached and cached.get("count") == count and cached.get("index"))


def scp_object_maps(scene, root_name):
    key = _index_key(root_name)
    count = 0 if scene is None else len(scene.objects)
    cached = scene_cache_get(scene, key)
    if _cached_index_ok(cached, count):
        return cached["index"]
    index = _build_scp_object_maps(scene, root_name)
    scene_cache_set(scene, key, {"count": count, "index": index})
    return index


def _build_scp_object_maps(scene, root_name):
    index = {"transform": {}, "geometry": {}, "bound": {}}
    for obj in iter_bound_scp_objects(scene, root_name):
        sid = as_id(obj.get("af_scp_id"))
        _index_bound_obj(index, sid, as_id(obj.get("af_scp_bound_id")), obj)
        _index_transform_obj(index, sid, obj)
        _index_geometry_obj(index, sid, obj)
    return index


def _bound_obj_key(scp_id, bound_id):
    sid, bid = as_id(scp_id), as_id(bound_id)
    return "" if not sid or not bid else f"{sid}:{bid}"


def _index_bound_obj(index, sid, bid, obj):
    key = _bound_obj_key(sid, bid)
    if key and key not in index["bound"]:
        index["bound"][key] = obj


def _index_transform_obj(index, sid, obj):
    if sid and obj.get("af_scp_transform") and sid not in index["transform"]:
        index["transform"][sid] = obj


def _index_geometry_obj(index, sid, obj):
    if sid and obj.type == "MESH" and obj.get("af_scp_geometry") and sid not in index["geometry"]:
        index["geometry"][sid] = obj


def find_geometry_scp_obj(scene, root_name, scp_id):
    sid = as_id(scp_id)
    objs = iter_bound_scp_objects(scene, root_name)
    return next((obj for obj in objs if obj.get("af_scp_geometry") and as_id(obj.get("af_scp_id")) == sid), None)


def indexed_geometry_mesh_scp_obj(index, scp_id):
    return dict(index.get("geometry", {})).get(as_id(scp_id))


def find_geometry_mesh_scp_obj(scene, root_name, scp_id):
    sid = as_id(scp_id)
    objs = iter_geometry_mesh_scp_objects(scene, root_name)
    return next((obj for obj in objs if as_id(obj.get("af_scp_id")) == sid), None)


def indexed_bound_scp_obj(index, scp_id, bound_id):
    return dict(index.get("bound", {})).get(_bound_obj_key(scp_id, bound_id))


def indexed_transform_scp_obj(index, scp_id):
    return dict(index.get("transform", {})).get(as_id(scp_id))


def find_transform_scp_obj(scene, root_name, scp_id):
    sid = as_id(scp_id)
    objs = iter_bound_scp_objects(scene, root_name)
    return next((obj for obj in objs if obj.get("af_scp_transform") and as_id(obj.get("af_scp_id")) == sid), None)


def find_bound_scp_obj_by_id(scene, root_name, scp_id, bound_id):
    return indexed_bound_scp_obj(scp_object_maps(scene, root_name), scp_id, bound_id)


def find_primary_scp_obj(scene, root_name, scp_id):
    return find_transform_scp_obj(scene, root_name, scp_id) or find_geometry_scp_obj(scene, root_name, scp_id) or _first_bound_scp_obj(scene, root_name, scp_id)


def _first_bound_scp_obj(scene, root_name, scp_id):
    sid = as_id(scp_id)
    objs = iter_bound_scp_objects(scene, root_name)
    return next((obj for obj in objs if as_id(obj.get("af_scp_id")) == sid), None)


def scp_prop_map(root):
    scene = scene_for_id(root)
    cached = scene_cache_get(scene, _prop_key(root))
    stamp = _scp_ids(root)
    if cached and cached.get("stamp") == stamp:
        return cached["index"]
    index = {as_id(s.id): s for s in root.af_scp_system.scps}
    scene_cache_set(scene, _prop_key(root), {"stamp": stamp, "index": index})
    return index


def find_scp_by_id(root, scp_id):
    return scp_prop_map(root).get(as_id(scp_id))


def scp_for_object(root, obj):
    sid = "" if obj is None else as_id(obj.get("af_scp_id"))
    return None if not sid else find_scp_by_id(root, sid)


def find_scp_index(root, scp_id):
    sid = as_id(scp_id)
    for index, scp in enumerate(root.af_scp_system.scps):
        if as_id(scp.id) == sid:
            return index
    return -1


def payload_id_set(payload, key):
    values = dict(payload or {}).get(str(key), ())
    return {as_id(value) for value in set(values or ()) if as_id(value)}
