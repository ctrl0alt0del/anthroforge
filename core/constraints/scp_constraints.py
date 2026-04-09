
import math

def _get_scp_by_id(root, scp_id):
    for s in root.af_scp_system.scps:
        if s.id == scp_id:
            return s
    return None


def _get_source_value(scp, key):
    if key == "PAR_SIZE_X":
        return float(scp.parallelepiped_size[0])
    if key == "PAR_SIZE_Y":
        return float(scp.parallelepiped_size[1])
    if key == "PAR_SIZE_Z":
        return float(scp.parallelepiped_size[2])
    if key == "PAR_BEND_RADIUS":
        return float(scp.parallelepiped_bend_radius)
    if key == "PAR_BEND_ANGLE":
        return float(scp.parallelepiped_bend_angle_deg)
    if key == "PAR_RESOLUTION":
        return float(scp.parallelepiped_resolution)
    if key == "ELL_RAD_X":
        return float(scp.ellipsoid_radii[0])
    if key == "ELL_RAD_Y":
        return float(scp.ellipsoid_radii[1])
    if key == "ELL_RAD_Z":
        return float(scp.ellipsoid_radii[2])
    if key == "CURVE_LENGTH":
        return float(scp.curve_length)
    if key == "LOCAL_SCALE_X":
        return float(scp.local_scale[0])
    if key == "LOCAL_SCALE_Y":
        return float(scp.local_scale[1])
    if key == "LOCAL_SCALE_Z":
        return float(scp.local_scale[2])
    return None


def _set_dest_value(scp, key, value):
    if key == "PAR_BEND_RADIUS":
        return _set_float_attr(scp, "parallelepiped_bend_radius", value, lo=0.001)
    if key == "PAR_BEND_ANGLE":
        return _set_float_attr(scp, "parallelepiped_bend_angle_deg", value, lo=-360.0, hi=360.0)
    if key == "PAR_RESOLUTION":
        return _set_int_attr(scp, "parallelepiped_resolution", value, lo=1, hi=64)
    scale_axis = {"LOCAL_SCALE_X": 0, "LOCAL_SCALE_Y": 1, "LOCAL_SCALE_Z": 2}.get(key, None)
    return _set_scale_axis(scp, scale_axis, value) if scale_axis is not None else False


def _set_float_attr(scp, attr, value, lo=None, hi=None):
    old = float(getattr(scp, attr))
    new = float(value)
    if lo is not None:
        new = max(lo, new)
    if hi is not None:
        new = min(hi, new)
    if abs(new - old) <= 1e-9:
        return False
    setattr(scp, attr, new)
    return True


def _set_int_attr(scp, attr, value, lo=None, hi=None):
    old = int(getattr(scp, attr))
    new = int(round(float(value)))
    if lo is not None:
        new = max(lo, new)
    if hi is not None:
        new = min(hi, new)
    if new == old:
        return False
    setattr(scp, attr, new)
    return True


def _set_scale_axis(scp, axis, value):
    old = float(scp.local_scale[axis])
    new = max(1e-6, float(value))
    if abs(new - old) <= 1e-9:
        return False
    sc = list(scp.local_scale)
    sc[axis] = new
    scp.local_scale = tuple(sc)
    return True


def _get_dest_value(scp, key):
    if key == "PAR_BEND_RADIUS":
        return float(scp.parallelepiped_bend_radius)
    if key == "PAR_BEND_ANGLE":
        return float(scp.parallelepiped_bend_angle_deg)
    if key == "PAR_RESOLUTION":
        return float(scp.parallelepiped_resolution)
    if key == "LOCAL_SCALE_X":
        return float(scp.local_scale[0])
    if key == "LOCAL_SCALE_Y":
        return float(scp.local_scale[1])
    if key == "LOCAL_SCALE_Z":
        return float(scp.local_scale[2])
    return None


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


def apply_scp_input_write(root, scp_id, dest_prop, value):
    dest = _get_scp_by_id(root, scp_id)
    if dest is None:
        return False
    return _set_dest_value(dest, dest_prop, value)


def evaluate_scp_constraints_runtime(root, changed_source_ids, is_cyclic_pair, delayed_writer):
    """
    Runtime evaluator for SCP constraints using cycle policy callback.
    - is_cyclic_pair(src_id, dst_id) -> bool
    - delayed_writer(entity_type, entity_id, input_port, value) -> None
    Returns set of changed destination SCP ids (immediate writes only).
    """
    changed_source_ids = set(changed_source_ids or [])
    if not changed_source_ids:
        return set()

    items = _collect_runtime_items(root, changed_source_ids)
    items.sort(key=lambda x: (x[0], x[1]))
    changed_dests = set()

    for _prio, _dst_sort, dest, c, src_id in items:
        _evaluate_single_constraint(root, is_cyclic_pair, delayed_writer, changed_dests, dest, c, src_id)
    return changed_dests


def _evaluate_single_constraint(root, is_cyclic_pair, delayed_writer, changed_dests, dest, c, src_id):
    src = _get_scp_by_id(root, src_id)
    if src is None:
        return
    source_key = c.arc_source_width_prop if c.calculator_type == "ARC_BRIDGE" else c.source_prop
    src_value = _get_source_value(src, source_key)
    if src_value is None:
        return
    cyclic = bool(is_cyclic_pair(src_id, dest.id))
    if c.calculator_type == "ARC_BRIDGE":
        _apply_arc_bridge_constraint(c, dest, src_value, cyclic, delayed_writer, changed_dests)
    else:
        _apply_linear_like_constraint(c, dest, src_value, cyclic, delayed_writer, changed_dests)
    c.runtime_status = "DELAYED_CYCLE" if cyclic else "OK"
    c.runtime_message = "Part of cycle, applied next tick" if cyclic else ""


def _collect_runtime_items(root, changed_source_ids):
    items = []
    for dest in root.af_scp_system.scps:
        for c in dest.constraints:
            if not bool(c.enabled):
                continue
            src_obj = getattr(c, "source_obj", None)
            src_id = str(src_obj.get("af_scp_id")) if (src_obj and src_obj.get("af_scp_id")) else str(getattr(c, "source_scp_id", "") or "")
            if not src_id or src_id == str(dest.id):
                continue
            if src_id and src_id in changed_source_ids:
                items.append((int(c.priority), str(dest.id), dest, c, src_id))
    return items


def _apply_arc_bridge_constraint(c, dest, src_value, cyclic, delayed_writer, changed_dests):
    dst_key_a = c.arc_dest_angle_prop
    if not bool(getattr(c, "delta_initialized", False)):
        dst_now_r = _get_dest_value(dest, "PAR_BEND_RADIUS")
        dst_now_a = _get_dest_value(dest, dst_key_a)
        if dst_now_r is None or dst_now_a is None:
            return
        c.delta_src_base = float(src_value)
        c.delta_dst_base = float(dst_now_r)
        c.delta_dst_base_2 = float(dst_now_a)
        c.delta_initialized = True
        return

    width_scale = float(getattr(c, "arc_width_scale", 1.0))
    width_offset = float(getattr(c, "arc_width_offset", 0.0))
    full_angle = max(1e-6, float(getattr(c, "arc_full_angle", 360.0)))
    width_now = max(0.0, float(src_value) * width_scale + width_offset)
    width_base = max(0.0, float(c.delta_src_base) * width_scale + width_offset)
    fixed_radius = max(1e-6, float(c.delta_dst_base))
    target_a_now = _arc_target_angle(full_angle, width_now, fixed_radius)
    target_a_base = _arc_target_angle(full_angle, width_base, fixed_radius)
    target_a = float(c.delta_dst_base_2) + (target_a_now - target_a_base)
    if cyclic:
        delayed_writer("SCP", dest.id, dst_key_a, target_a)
    elif _set_dest_value(dest, dst_key_a, target_a):
        changed_dests.add(dest.id)


def _arc_target_angle(full_angle, width, radius):
    ratio = max(-1.0, min(1.0, width / (2.0 * radius)))
    gap_deg = math.degrees(2.0 * math.asin(ratio))
    return full_angle - gap_deg


def _apply_linear_like_constraint(c, dest, src_value, cyclic, delayed_writer, changed_dests):
    if not bool(getattr(c, "delta_initialized", False)):
        dst_now = _get_dest_value(dest, c.dest_prop)
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
        delayed_writer("SCP", dest.id, c.dest_prop, target)
    elif _set_dest_value(dest, c.dest_prop, target):
        changed_dests.add(dest.id)
