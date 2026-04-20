from dataclasses import dataclass
from mathutils import Vector


@dataclass(frozen=True)
class MirrorRole:
    is_source: bool
    is_target: bool
    source_id: str
    propagate_source_id: str


def _is_source_scp(scp_prop):
    return bool(getattr(scp_prop, "mirror_enabled", False))


def _shape_is_source(shape):
    if shape is None:
        return False
    fn = getattr(shape, "is_mirror_source", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    return False


def _parent_id(scp_prop):
    return str(getattr(scp_prop, "parent_id", "") or "")


def _is_source_id(scp_id, scp_map, shape_by_id):
    sid = str(scp_id or "")
    shape = (shape_by_id or {}).get(sid)
    if _shape_is_source(shape):
        return True
    scp_prop = scp_map.get(sid)
    return _is_source_scp(scp_prop) if scp_prop is not None else False


def build_scp_mirror_roles(scp_map, shape_by_id=None):
    roles = {}

    def resolve(scp_id, trail):
        sid = str(scp_id or "")
        if not sid:
            return MirrorRole(False, False, "", "")
        cached = roles.get(sid)
        if cached is not None:
            return cached
        if sid in trail:
            out = MirrorRole(False, False, "", "")
            roles[sid] = out
            return out

        scp = scp_map.get(sid)
        if scp is None:
            out = MirrorRole(False, False, "", "")
            roles[sid] = out
            return out

        source_self = _is_source_id(sid, scp_map, shape_by_id)
        pid = _parent_id(scp)
        parent_role = resolve(pid, trail | {sid}) if pid else MirrorRole(False, False, "", "")
        parent_source = str(getattr(parent_role, "propagate_source_id", "") or "")

        if source_self:
            target_source = parent_source
            out = MirrorRole(
                True,
                bool(target_source),
                str(target_source or ""),
                sid,
            )
        else:
            src = parent_source
            out = MirrorRole(False, bool(src), str(src or ""), str(src or ""))

        roles[sid] = out
        return out

    for sid in list(scp_map.keys()):
        resolve(sid, set())
    return roles


def axis_index(axis):
    a = str(axis or "X").upper()
    if a == "Y":
        return 1
    if a == "Z":
        return 2
    return 0


def source_axis_for_scp(scp_prop):
    return str(getattr(scp_prop, "mirror_axis", "X") or "X")


def _source_axis_for_id(source_scp_id, scp_map, shape_by_id):
    sid = str(source_scp_id or "")
    shape = (shape_by_id or {}).get(sid)
    if shape is not None:
        fn = getattr(shape, "mirror_axis", None)
        if callable(fn):
            try:
                return str(fn() or "X")
            except Exception:
                pass
    scp_prop = scp_map.get(sid)
    if scp_prop is None:
        return "X"
    return source_axis_for_scp(scp_prop)


def source_rule_for_scp(sync, scp_col, root_name, source_scp_id, scp_map, shape_by_id=None):
    source_prop = scp_map.get(str(source_scp_id or ""))
    if source_prop is None:
        return None
    if not _is_source_id(source_scp_id, scp_map, shape_by_id):
        return None

    axis = _source_axis_for_id(source_scp_id, scp_map, shape_by_id)
    src = sync._find_source_scp_obj(scp_col, root_name, source_scp_id)
    if src is None:
        return None

    ax = axis_index(axis)
    corners = list(getattr(src, "bound_box", []) or [])
    if not corners:
        loc = src.matrix_world.translation
        origin = [float(loc.x), float(loc.y), float(loc.z)]
        return axis, tuple(origin)

    world_corners = [src.matrix_world @ Vector(c) for c in corners]
    coords = [float(v[ax]) for v in world_corners]
    mid = 0.5 * (min(coords) + max(coords))
    loc = src.matrix_world.translation
    origin = [float(loc.x), float(loc.y), float(loc.z)]
    origin[ax] = mid
    return axis, tuple(origin)


def source_rules_by_scp_id(sync, scp_col, root_name, scp_map, roles, shape_by_id=None):
    out = {}
    for sid, role in roles.items():
        if not bool(getattr(role, "is_source", False)):
            continue
        rule = source_rule_for_scp(sync, scp_col, root_name, sid, scp_map, shape_by_id=shape_by_id)
        if rule is not None:
            out[sid] = rule
    return out


def target_rule_for_scp(scp_id, roles, source_rules):
    role = roles.get(str(scp_id or ""))
    if role is None or not bool(getattr(role, "is_target", False)):
        return None
    src = str(getattr(role, "source_id", "") or "")
    if not src:
        return None
    return source_rules.get(src)


def target_rule_for_fiber(fiber_prop, roles, source_rules):
    parent_ids = []
    if getattr(fiber_prop, "a_parent_id", ""):
        parent_ids.append(str(fiber_prop.a_parent_id))
    if getattr(fiber_prop, "b_parent_id", ""):
        parent_ids.append(str(fiber_prop.b_parent_id))
    for tp in getattr(fiber_prop, "mid_touches", []):
        pid = str(getattr(tp, "parent_id", "") or "")
        if pid:
            parent_ids.append(pid)

    for sid in parent_ids:
        role = roles.get(sid)
        if role is None:
            continue
        if bool(getattr(role, "is_source", False)):
            rule = source_rules.get(sid)
            if rule is not None:
                return rule
        src = str(getattr(role, "source_id", "") or "")
        if src:
            rule = source_rules.get(src)
            if rule is not None:
                return rule
    return None


def target_rule_for_muscle(muscle_prop, fibers_by_id, roles, source_rules):
    for ref in getattr(muscle_prop, "fiber_refs", []):
        fid = str(getattr(ref, "fiber_id", "") or "")
        if not fid:
            continue
        fiber = fibers_by_id.get(fid)
        if fiber is None:
            continue
        rule = target_rule_for_fiber(fiber, roles, source_rules)
        if rule is not None:
            return rule
    return None
