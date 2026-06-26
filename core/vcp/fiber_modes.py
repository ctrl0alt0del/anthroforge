OPEN_TOPOLOGY = "OPEN"
LOOP_TOPOLOGY = "LOOP"
SOLVED_GENERATION = "SOLVED"
DERIVED_GENERATION = "DERIVED"


def fiber_topology_mode(fiber):
    return str(getattr(fiber, "topology_mode", OPEN_TOPOLOGY) or OPEN_TOPOLOGY)


def fiber_generation_mode(fiber):
    return str(getattr(fiber, "generation_mode", SOLVED_GENERATION) or SOLVED_GENERATION)


def is_loop_fiber(fiber):
    return fiber_topology_mode(fiber) == LOOP_TOPOLOGY


def is_open_fiber(fiber):
    return fiber_topology_mode(fiber) == OPEN_TOPOLOGY


def is_solved_loop(fiber):
    return is_loop_fiber(fiber) and fiber_generation_mode(fiber) == SOLVED_GENERATION


def is_derived_loop(fiber):
    return is_loop_fiber(fiber) and fiber_generation_mode(fiber) == DERIVED_GENERATION


def driver_fiber_id(fiber):
    return str(getattr(fiber, "driver_fiber_id", "") or "")


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


def fibers_by_id(root):
    return {str(fiber.id or ""): fiber for fiber in getattr(getattr(root, "af_vcp_system", None), "fibers", ())}


def fiber_root_id(fiber, fiber_map):
    root = str(getattr(fiber, "id", "") or "")
    seen = set()
    while is_derived_loop(fiber) and driver_fiber_id(fiber) in fiber_map and driver_fiber_id(fiber) not in seen:
        seen.add(root)
        root = driver_fiber_id(fiber)
        fiber = fiber_map[root]
    return root


def fiber_root(fiber, fiber_map):
    return fiber_map.get(fiber_root_id(fiber, fiber_map))


def derived_children(fibers, fiber_id):
    target = str(fiber_id or "")
    return [fiber for fiber in tuple(fibers or ()) if driver_fiber_id(fiber) == target]
