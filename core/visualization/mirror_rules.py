from mathutils import Matrix, Vector

from ..vcp.fiber_modes import fiber_parent_ids, fiber_root


def axis_to_scale(axis: str):
    a = (axis or "X").upper()
    if a == "Y":
        return (1.0, -1.0, 1.0)
    if a == "Z":
        return (1.0, 1.0, -1.0)
    return (-1.0, 1.0, 1.0)


def mirror_matrix(axis="X", origin=(0.0, 0.0, 0.0)):
    o = origin if isinstance(origin, Vector) else Vector(origin)
    sx, sy, sz = axis_to_scale(axis)
    s = Matrix.Diagonal((sx, sy, sz, 1.0))
    return Matrix.Translation(o) @ s @ Matrix.Translation(-o)


def mirror_world_matrix(world_matrix, axis="X", origin=(0.0, 0.0, 0.0)):
    return mirror_matrix(axis=axis, origin=origin) @ world_matrix


def explicit_mirror_rule_for_scp(scp_prop):
    if not bool(getattr(scp_prop, "mirror_enabled", False)):
        return None
    axis = getattr(scp_prop, "mirror_axis", "X")
    origin = tuple(getattr(scp_prop, "mirror_origin", (0.0, 0.0, 0.0)))
    return axis, origin


def effective_rule_for_scp(scp_id, scp_map):
    seen = set()
    cur = scp_id
    while cur and cur not in seen:
        seen.add(cur)
        s = scp_map.get(cur)
        if s is None:
            return None
        rule = explicit_mirror_rule_for_scp(s)
        if rule is not None:
            return rule
        if not bool(getattr(s, "mirror_inherit_parent", True)):
            return None
        cur = s.parent_id or ""
    return None


def _first_scp_rule(parent_ids, scp_map):
    for pid in parent_ids:
        rule = effective_rule_for_scp(pid, scp_map)
        if rule is not None:
            return rule
    return None


def effective_rule_for_fiber(fiber_prop, scp_map, fibers_by_id=None):
    parent_ids = fiber_parent_ids(fiber_prop)
    if parent_ids:
        return _first_scp_rule(parent_ids, scp_map)
    root = None if fibers_by_id is None else fiber_root(fiber_prop, fibers_by_id)
    return None if root is None or root == fiber_prop else _first_scp_rule(fiber_parent_ids(root), scp_map)


def effective_rule_for_muscle(muscle_prop, fibers_by_id, scp_map):
    for ref in muscle_prop.fiber_refs:
        f = fibers_by_id.get(ref.fiber_id)
        if f is None:
            continue
        r = effective_rule_for_fiber(f, scp_map, fibers_by_id)
        if r is not None:
            return r
    return None


def axis_index(axis):
    a = (axis or "X").upper()
    if a == "Y":
        return 1
    if a == "Z":
        return 2
    return 0


def intersects_mirror_plane(obj, axis="X", origin=(0.0, 0.0, 0.0), eps=1e-6):
    if obj is None or obj.type not in {"MESH", "CURVE"}:
        return False
    ax = axis_index(axis)
    o = float(origin[ax]) if hasattr(origin, "__len__") else 0.0
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    vals = [c[ax] - o for c in corners]
    return (min(vals) <= eps and max(vals) >= -eps)
