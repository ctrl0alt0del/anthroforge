
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
        old = float(scp.parallelepiped_bend_radius)
        new = max(0.001, float(value))
        if abs(new - old) <= 1e-9:
            return False
        scp.parallelepiped_bend_radius = new
        return True

    if key == "PAR_BEND_ANGLE":
        old = float(scp.parallelepiped_bend_angle_deg)
        new = max(-360.0, min(360.0, float(value)))
        if abs(new - old) <= 1e-9:
            return False
        scp.parallelepiped_bend_angle_deg = new
        return True

    if key == "PAR_RESOLUTION":
        old = int(scp.parallelepiped_resolution)
        new = max(1, min(64, int(round(float(value)))))
        if new == old:
            return False
        scp.parallelepiped_resolution = new
        return True

    if key == "LOCAL_SCALE_X":
        old = float(scp.local_scale[0])
        new = max(1e-6, float(value))
        if abs(new - old) <= 1e-9:
            return False
        sc = list(scp.local_scale)
        sc[0] = new
        scp.local_scale = tuple(sc)
        return True

    if key == "LOCAL_SCALE_Y":
        old = float(scp.local_scale[1])
        new = max(1e-6, float(value))
        if abs(new - old) <= 1e-9:
            return False
        sc = list(scp.local_scale)
        sc[1] = new
        scp.local_scale = tuple(sc)
        return True

    if key == "LOCAL_SCALE_Z":
        old = float(scp.local_scale[2])
        new = max(1e-6, float(value))
        if abs(new - old) <= 1e-9:
            return False
        sc = list(scp.local_scale)
        sc[2] = new
        scp.local_scale = tuple(sc)
        return True

    return False


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

    items = []
    for dest in root.af_scp_system.scps:
        for c in dest.constraints:
            if not bool(c.enabled):
                continue
            src_id = ""
            src_obj = getattr(c, "source_obj", None)
            if src_obj and src_obj.get("af_scp_id"):
                src_id = str(src_obj.get("af_scp_id"))
            else:
                src_id = str(getattr(c, "source_scp_id", "") or "")
            if not src_id or src_id not in changed_source_ids:
                continue
            items.append((int(c.priority), str(dest.id), dest, c, src_id))

    items.sort(key=lambda x: (x[0], x[1]))
    changed_dests = set()

    for _prio, _dst_sort, dest, c, src_id in items:
        src = _get_scp_by_id(root, src_id)
        if src is None:
            continue

        source_key = c.arc_source_width_prop if c.calculator_type == "ARC_BRIDGE" else c.source_prop
        src_value = _get_source_value(src, source_key)
        if src_value is None:
            continue

        cyclic = bool(is_cyclic_pair(src_id, dest.id))
        status = "DELAYED_CYCLE" if cyclic else "OK"
        msg = "Part of cycle, applied next tick" if cyclic else ""

        if c.calculator_type == "ARC_BRIDGE":
            dst_key_a = c.arc_dest_angle_prop

            if not bool(getattr(c, "delta_initialized", False)):
                dst_now_r = _get_dest_value(dest, "PAR_BEND_RADIUS")
                dst_now_a = _get_dest_value(dest, dst_key_a)
                if dst_now_r is None or dst_now_a is None:
                    continue
                c.delta_src_base = float(src_value)
                c.delta_dst_base = float(dst_now_r)
                c.delta_dst_base_2 = float(dst_now_a)
                c.delta_initialized = True
                c.runtime_status = status
                c.runtime_message = msg
                continue

            width_scale = float(getattr(c, "arc_width_scale", 1.0))
            width_offset = float(getattr(c, "arc_width_offset", 0.0))
            full_angle = max(1e-6, float(getattr(c, "arc_full_angle", 360.0)))

            width_now = max(0.0, float(src_value) * width_scale + width_offset)
            width_base = max(0.0, float(c.delta_src_base) * width_scale + width_offset)
            fixed_radius = max(1e-6, float(c.delta_dst_base))

            ratio_now = max(-1.0, min(1.0, width_now / (2.0 * fixed_radius)))
            gap_deg_now = math.degrees(2.0 * math.asin(ratio_now))
            target_a_now = full_angle - gap_deg_now

            ratio_base = max(-1.0, min(1.0, width_base / (2.0 * fixed_radius)))
            gap_deg_base = math.degrees(2.0 * math.asin(ratio_base))
            target_a_base = full_angle - gap_deg_base
            target_a = float(c.delta_dst_base_2) + (target_a_now - target_a_base)

            if cyclic:
                delayed_writer("SCP", dest.id, dst_key_a, target_a)
            else:
                did_a = _set_dest_value(dest, dst_key_a, target_a)
                if did_a:
                    changed_dests.add(dest.id)

            c.runtime_status = status
            c.runtime_message = msg
            continue

        # LINEAR / RANGE_REMAP
        if not bool(getattr(c, "delta_initialized", False)):
            dst_now = _get_dest_value(dest, c.dest_prop)
            if dst_now is None:
                continue
            c.delta_src_base = float(src_value)
            c.delta_dst_base = float(dst_now)
            c.delta_initialized = True
            c.runtime_status = status
            c.runtime_message = msg
            continue

        f_now = _eval_constraint_value(c, src_value)
        f_base = _eval_constraint_value(c, float(c.delta_src_base))
        target = float(c.delta_dst_base) + (f_now - f_base)

        if cyclic:
            delayed_writer("SCP", dest.id, c.dest_prop, target)
        else:
            did = _set_dest_value(dest, c.dest_prop, target)
            if did:
                changed_dests.add(dest.id)

        c.runtime_status = status
        c.runtime_message = msg

    return changed_dests


def apply_scp_constraints(root, changed_source_ids):
    """
    Apply constraints where source_scp_id in changed_source_ids.
    Constraints are attached to destination SCPs.
    Returns set of destination SCP ids that changed.
    """
    changed_source_ids = set(changed_source_ids or [])
    if not changed_source_ids:
        return set()

    items = []
    for dest in root.af_scp_system.scps:
        for c in dest.constraints:
            if not bool(c.enabled):
                continue
            src_id = ""
            src_obj = getattr(c, "source_obj", None)
            if src_obj and src_obj.get("af_scp_id"):
                src_id = str(src_obj.get("af_scp_id"))
            else:
                src_id = str(getattr(c, "source_scp_id", "") or "")
            if not src_id:
                continue
            if src_id not in changed_source_ids:
                continue
            items.append((int(c.priority), dest, c, src_id))

    items.sort(key=lambda x: x[0])

    changed_dests = set()
    for _prio, dest, c, src_id in items:
        src = _get_scp_by_id(root, src_id)
        if src is None:
            continue

        source_key = c.arc_source_width_prop if c.calculator_type == "ARC_BRIDGE" else c.source_prop
        src_value = _get_source_value(src, source_key)
        if src_value is None:
            continue

        if c.calculator_type == "ARC_BRIDGE":
            dst_key_a = c.arc_dest_angle_prop

            # Delta mode baseline capture for dual-output calculator.
            if not bool(getattr(c, "delta_initialized", False)):
                dst_now_r = _get_dest_value(dest, "PAR_BEND_RADIUS")
                dst_now_a = _get_dest_value(dest, dst_key_a)
                if dst_now_r is None or dst_now_a is None:
                    continue
                c.delta_src_base = float(src_value)
                c.delta_dst_base = float(dst_now_r)
                c.delta_dst_base_2 = float(dst_now_a)
                c.delta_initialized = True
                continue

            width_scale = float(getattr(c, "arc_width_scale", 1.0))
            width_offset = float(getattr(c, "arc_width_offset", 0.0))
            full_angle = max(1e-6, float(getattr(c, "arc_full_angle", 360.0)))

            width_now = max(0.0, float(src_value) * width_scale + width_offset)
            width_base = max(0.0, float(c.delta_src_base) * width_scale + width_offset)

            # ARC_BRIDGE mode: width drives angle only; radius stays at baseline.
            fixed_radius = max(1e-6, float(c.delta_dst_base))

            ratio_now = max(-1.0, min(1.0, width_now / (2.0 * fixed_radius)))
            gap_deg_now = math.degrees(2.0 * math.asin(ratio_now))
            target_a_now = full_angle - gap_deg_now

            ratio_base = max(-1.0, min(1.0, width_base / (2.0 * fixed_radius)))
            gap_deg_base = math.degrees(2.0 * math.asin(ratio_base))
            target_a_base = full_angle - gap_deg_base

            target_a = float(c.delta_dst_base_2) + (target_a_now - target_a_base)

            # Keep radius fixed at captured baseline.
            did_a = _set_dest_value(dest, dst_key_a, target_a)
            if did_a:
                changed_dests.add(dest.id)
        else:
            # Delta mode:
            # dest = dest_base + (f(src_now) - f(src_base))
            if not bool(getattr(c, "delta_initialized", False)):
                dst_now = _get_dest_value(dest, c.dest_prop)
                if dst_now is None:
                    continue
                c.delta_src_base = float(src_value)
                c.delta_dst_base = float(dst_now)
                c.delta_initialized = True
                continue

            f_now = _eval_constraint_value(c, src_value)
            f_base = _eval_constraint_value(c, float(c.delta_src_base))
            target = float(c.delta_dst_base) + (f_now - f_base)

            did = _set_dest_value(dest, c.dest_prop, target)
            if did:
                changed_dests.add(dest.id)

    return changed_dests
