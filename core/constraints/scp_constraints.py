import bpy

from ..deps.conflict_resolver import resolve_conflict


def _get_scp_by_id(root, scp_id):
    for s in root.af_scp_system.scps:
        if s.id == scp_id:
            return s
    return None


def _first_scene_for_root(root):
    for scene in bpy.data.scenes:
        if scene.objects.get(getattr(root, "name", "")) is root:
            return scene
    return bpy.context.scene


def _get_scp_object(root, scp_id, scene=None):
    scene = scene or _first_scene_for_root(root)
    if scene is None:
        return None
    rid = str(getattr(root, "name", "") or "")
    sid = str(scp_id or "")
    for obj in scene.objects:
        if (
            obj.get("af_scp")
            and not obj.get("af_scp_mirror")
            and obj.get("af_root_name") == rid
            and str(obj.get("af_scp_id") or "") == sid
        ):
            return obj
    return None


def _get_source_value(obj, key):
    key = str(key or "")
    if key == "LOC_X":
        return float(obj.location.x)
    if key == "LOC_Y":
        return float(obj.location.y)
    if key == "LOC_Z":
        return float(obj.location.z)
    if key == "ROT_X":
        return float(obj.rotation_euler.x)
    if key == "ROT_Y":
        return float(obj.rotation_euler.y)
    if key == "ROT_Z":
        return float(obj.rotation_euler.z)
    if key == "SCALE_X":
        return float(obj.scale.x)
    if key == "SCALE_Y":
        return float(obj.scale.y)
    if key == "SCALE_Z":
        return float(obj.scale.z)
    if key == "DIM_X":
        return float(obj.dimensions.x)
    if key == "DIM_Y":
        return float(obj.dimensions.y)
    if key == "DIM_Z":
        return float(obj.dimensions.z)
    return None


def _set_dest_value(obj, key, value, source="deps_constraint"):
    key = str(key or "")
    if key == "LOC_X":
        return _set_axis(obj, "location", 0, value, source=source)
    if key == "LOC_Y":
        return _set_axis(obj, "location", 1, value, source=source)
    if key == "LOC_Z":
        return _set_axis(obj, "location", 2, value, source=source)
    if key == "ROT_X":
        return _set_axis(obj, "rotation_euler", 0, value, source=source)
    if key == "ROT_Y":
        return _set_axis(obj, "rotation_euler", 1, value, source=source)
    if key == "ROT_Z":
        return _set_axis(obj, "rotation_euler", 2, value, source=source)
    if key == "SCALE_X":
        return _set_axis(obj, "scale", 0, value, lo=1e-6, source=source)
    if key == "SCALE_Y":
        return _set_axis(obj, "scale", 1, value, lo=1e-6, source=source)
    if key == "SCALE_Z":
        return _set_axis(obj, "scale", 2, value, lo=1e-6, source=source)
    return False


def _set_axis(obj, attr, axis, value, lo=None, hi=None, source="deps_constraint"):
    vec = getattr(obj, attr)
    old = float(vec[axis])
    new = float(value)
    if lo is not None:
        new = max(lo, new)
    if hi is not None:
        new = min(hi, new)

    sid = str(obj.get("af_scp_id") or "")
    resolved = resolve_conflict(
        entity_type="SCP",
        entity_id=sid,
        aspect=f"obj.{attr}[{int(axis)}]",
        source=source,
        current=old,
        incoming=new,
        payload={"attr": str(attr), "axis": int(axis)},
    )
    try:
        new = float(resolved)
    except Exception:
        new = old
    if lo is not None:
        new = max(lo, new)
    if hi is not None:
        new = min(hi, new)

    if abs(new - old) <= 1e-9:
        return False

    cur = list(vec)
    cur[axis] = new
    setattr(obj, attr, tuple(cur))
    return True


def _get_dest_value(obj, key):
    return _get_source_value(obj, key)


def _eval_constraint_value(c, src):
    if c.calculator_type == "RANGE_REMAP":
        in_min = float(c.in_min)
        in_max = float(c.in_max)
        out_min = float(c.out_min)
        out_max = float(c.out_max)
        if abs(in_max - in_min) <= 1e-12:
            t = 0.0
        else:
            t = (float(src) - in_min) / (in_max - in_min)
        if bool(c.clamp):
            t = max(0.0, min(1.0, t))
        return out_min + t * (out_max - out_min)

    a = float(c.linear_a)
    b = float(c.linear_b)
    return a * float(src) + b


def apply_scp_input_write(root, scp_id, dest_prop, value, source="deps_constraint", scene=None):
    dest = _get_scp_by_id(root, scp_id)
    if dest is None:
        return False
    obj = _get_scp_object(root, dest.id, scene=scene)
    if obj is None:
        return False
    return _set_dest_value(obj, dest_prop, value, source=source)


def evaluate_scp_constraints_runtime(root, changed_source_ids, is_cyclic_pair, delayed_writer, scene=None):
    changed_source_ids = set(changed_source_ids or [])
    if not changed_source_ids:
        return set()

    items = _collect_runtime_items(root, changed_source_ids)
    items.sort(key=lambda x: (x[0], x[1]))
    changed_dests = set()

    for _prio, _dst_sort, dest, c, src_id in items:
        _evaluate_single_constraint(root, scene, is_cyclic_pair, delayed_writer, changed_dests, dest, c, src_id)
    return changed_dests


def _evaluate_single_constraint(root, scene, is_cyclic_pair, delayed_writer, changed_dests, dest, c, src_id):
    src_obj = _get_scp_object(root, src_id, scene=scene)
    dst_obj = _get_scp_object(root, dest.id, scene=scene)
    if src_obj is None or dst_obj is None:
        return

    src_value = _get_source_value(src_obj, c.source_prop)
    if src_value is None:
        return

    cyclic = bool(is_cyclic_pair(src_id, dest.id))
    _apply_linear_like_constraint(c, dst_obj, src_value, cyclic, delayed_writer, changed_dests, dest.id)
    c.runtime_status = "DELAYED_CYCLE" if cyclic else "OK"
    c.runtime_message = "Part of cycle, applied next tick" if cyclic else ""


def _collect_runtime_items(root, changed_source_ids):
    items = []
    for dest in root.af_scp_system.scps:
        for c in dest.constraints:
            if not bool(c.enabled):
                continue
            src_obj = getattr(c, "source_obj", None)
            src_id = (
                str(src_obj.get("af_scp_id"))
                if (src_obj and src_obj.get("af_scp_id"))
                else str(getattr(c, "source_scp_id", "") or "")
            )
            if not src_id or src_id == str(dest.id):
                continue
            if src_id in changed_source_ids:
                items.append((int(c.priority), str(dest.id), dest, c, src_id))
    return items


def _apply_linear_like_constraint(c, dst_obj, src_value, cyclic, delayed_writer, changed_dests, dst_id):
    if not bool(getattr(c, "delta_initialized", False)):
        dst_now = _get_dest_value(dst_obj, c.dest_prop)
        if dst_now is None:
            return
        c.delta_src_base = float(src_value)
        c.delta_dst_base = float(dst_now)
        c.delta_initialized = True
        return

    f_now = _eval_constraint_value(c, src_value)
    f_base = _eval_constraint_value(c, float(c.delta_src_base))
    target = float(c.delta_dst_base) + (f_now - f_base)
    if cyclic:
        delayed_writer("SCP", dst_id, c.dest_prop, target)
    elif _set_dest_value(dst_obj, c.dest_prop, target):
        changed_dests.add(dst_id)
