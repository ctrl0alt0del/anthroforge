from mathutils import Matrix, Vector

from ..vcp.fiber_modes import fiber_parent_ids


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
    from ..vcp.attachment_surface import muscle_backed
    from .attachment_mirror_rules import for_fiber
    if muscle_backed(fiber_prop): return for_fiber(fiber_prop, scp_map)
    _ = fibers_by_id
    if hasattr(fiber_prop, "get") and fiber_prop.get("af_authoring_symmetry") == "explicit":
        return None
    parent_ids = mirror_parent_ids(fiber_prop)
    return authored_mirror_rule(fiber_prop) or _first_scp_rule(parent_ids, scp_map)


def authored_mirror_rule(fiber):
    if not hasattr(fiber, 'get') or fiber.get('af_authoring_symmetry') != 'native_mirror':
        return None
    axis, origin = fiber.get('af_authoring_mirror_axis'), fiber.get('af_authoring_mirror_origin')
    return (str(axis), tuple(origin)) if axis in ('X', 'Y', 'Z') and origin is not None and len(origin) == 3 else None


def mirror_parent_ids(fiber):
    from ..scp_runtime.common import attachment_dependency_id
    root = getattr(fiber, 'id_data', None)
    return [attachment_dependency_id(root, pid) if root and str(pid).startswith('AFI_') else pid
            for pid in fiber_parent_ids(fiber)]


def effective_rule_for_muscle(muscle_prop, fibers_by_id, scp_map):
    source = _muscle_surface_source(muscle_prop)
    for ref in source.fiber_refs:
        f = fibers_by_id.get(ref.fiber_id)
        if f is None:
            continue
        r = effective_rule_for_fiber(f, scp_map, fibers_by_id)
        if r is not None:
            return r
    return None


def _muscle_surface_source(muscle):
    if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) != "FIBER_SURFACE":
        return muscle
    root = getattr(muscle, "id_data", None)
    target = str(getattr(muscle, "fiber_surface_id", "") or "")
    surfaces = getattr(getattr(root, "af_vcp_system", None), "fiber_surfaces", ())
    return next((surface for surface in surfaces if str(surface.id) == target), muscle)


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
