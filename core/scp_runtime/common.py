from mathutils import Vector

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


def is_source_scp(obj, root_name):
    return bool(obj and obj.type == "MESH" and obj.get("af_scp") and not obj.get("af_scp_mirror") and obj.get("af_root_name") == root_name)


def iter_source_scps(scene, root_name):
    for obj in scene.objects:
        if is_source_scp(obj, root_name):
            yield obj


def find_source_scp_obj(scene, root_name, scp_id):
    sid = as_id(scp_id)
    return next((obj for obj in iter_source_scps(scene, root_name) if as_id(obj.get("af_scp_id")) == sid), None)


def scp_prop_map(root):
    return {as_id(s.id): s for s in root.af_scp_system.scps}


def find_scp_by_id(root, scp_id):
    sid = as_id(scp_id)
    return next((scp for scp in root.af_scp_system.scps if as_id(scp.id) == sid), None)


def find_scp_by_object_name(root, object_name):
    name = str(object_name or "")
    return next((scp for scp in root.af_scp_system.scps if str(getattr(scp, "object_name", "") or "") == name), None)


def find_scp_index(root, scp_id):
    sid = as_id(scp_id)
    for index, scp in enumerate(root.af_scp_system.scps):
        if as_id(scp.id) == sid:
            return index
    return -1


def payload_id_set(payload, key):
    values = dict(payload or {}).get(str(key), ())
    return {as_id(value) for value in set(values or ()) if as_id(value)}
