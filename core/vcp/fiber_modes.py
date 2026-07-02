OPEN_TOPOLOGY = "OPEN"
LOOP_TOPOLOGY = "LOOP"


def fiber_topology_mode(fiber):
    return str(getattr(fiber, "topology_mode", OPEN_TOPOLOGY) or OPEN_TOPOLOGY)


def is_loop_fiber(fiber):
    return fiber_topology_mode(fiber) == LOOP_TOPOLOGY


def is_open_fiber(fiber):
    return fiber_topology_mode(fiber) == OPEN_TOPOLOGY


def is_solved_loop(fiber):
    return is_loop_fiber(fiber)


def loop_anchor_specs(fiber):
    return [(str(item.parent_id or ""), str(item.attach_param or "")) for item in getattr(fiber, "loop_anchors", ())]


def _open_parent_ids(fiber):
    mids = [str(tp.parent_id or "") for tp in getattr(fiber, "mid_touches", ()) if str(tp.parent_id or "")]
    ends = [str(getattr(fiber, key, "") or "") for key in ("a_parent_id", "b_parent_id") if str(getattr(fiber, key, "") or "")]
    return ends + mids


def fiber_parent_ids(fiber):
    if is_loop_fiber(fiber):
        return [pid for pid, _raw in loop_anchor_specs(fiber) if pid]
    return _open_parent_ids(fiber)
