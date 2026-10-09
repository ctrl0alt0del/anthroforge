"""Shared, transient hard-anchor collision preflight for every Fiber engine."""

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from ..scp_runtime.common import iter_geometry_mesh_scp_objects
from .fiber_collision import CollisionOracle, _collider_stamp
from .fiber_modes import is_loop_fiber
from .v2.collision import (cached_native_collision_world,
                           cached_native_collision_world_batch,
                           collision_backend_status, native_batch_status)
from .v2.contracts import V2AnchorRole


_CACHE_LIMIT = 128
_OWNER_CONTACT_MODE = "AUTHORED_LOCAL"
_CACHE = OrderedDict()


@dataclass(frozen=True)
class FiberHardAnchor:
    point: tuple
    owner_id: str
    role: V2AnchorRole
    authored_index: int


@dataclass(frozen=True)
class FiberAnchorViolation:
    role: V2AnchorRole
    authored_index: int
    owner_id: str
    blocker_id: str
    relation: str
    point: tuple
    measured_clearance: float
    configured_clearance: float
    effective_clearance: float
    residual: float
    contained: bool
    action: str


@dataclass(frozen=True)
class FiberAnchorPreflightResult:
    valid: bool
    violations: tuple
    cache_key: tuple
    candidate_pairs: int
    tested_pairs: int
    anchors: tuple = ()


def preflight_fiber_hard_anchors(root, scene, fiber, solver, depsgraph, quality="FINAL"):
    probe = _probe_key(root, scene, fiber)
    cached = _CACHE.get(probe)
    if cached is not None:
        _CACHE.move_to_end(probe)
        _publish(root, scene, fiber, cached)
        return cached
    anchors, issue = _resolve_anchors(root, scene, fiber, solver, depsgraph)
    if issue or anchors is None:
        invalidate_fiber_anchor_preflight(scene, root, {getattr(fiber, "id", "")})
        return None
    return _compute_preflight(root, scene, fiber, depsgraph, quality, probe, anchors)


def preflight_fiber_hard_anchors_in_world(root, scene, fiber, solver, depsgraph,
                                          colliders, world, cache_key, quality="FINAL"):
    anchors, issue = _resolve_anchors(root, scene, fiber, solver, depsgraph)
    if issue or anchors is None: return None
    slack = _clearance_slack(colliders, fiber.collision_radius, quality)
    key = ("shared-hard-anchor", tuple(cache_key), str(fiber.id), _raw_anchor_specs(fiber))
    result = evaluate_anchor_preflight(anchors, colliders, _hierarchy(root),
                                       fiber.collision_radius, slack, key, world)
    _publish(root, scene, fiber, result)
    return result


def evaluate_anchor_preflight(anchors, colliders, hierarchy, configured, slack, cache_key=(), world=None):
    rows = tuple(anchors or ())
    effective = max(0.0, float(configured) - float(slack))
    world = world or _collision_world(tuple(colliders or ()), cache_key)
    batch = _contact_pairs(world, rows, effective)
    violations = _violations(rows, colliders, hierarchy, configured, effective, batch.pairs)
    return FiberAnchorPreflightResult(not violations, violations, tuple(cache_key),
                                      int(batch.candidate_pairs), int(batch.tested_pairs), rows)


def current_fiber_anchor_preflight(scene, root, fiber):
    from ..warnings.anchors import current
    return current(scene, root, fiber)


def fiber_anchor_scope(scene, root, fiber):
    from ..warnings.session import entity_reference
    return entity_reference(scene, root, fiber).scope


def anchor_preflight_summary(result):
    rows = tuple(getattr(result, "violations", ()) or ())
    count = len({(row.role, row.authored_index) for row in rows})
    noun = "anchor" if count == 1 else "anchors"
    return f"Fiber has {count} invalid hard {noun}; planning cannot start."


def invalidate_fiber_anchor_preflight(scene=None, root=None, fiber_ids=None):
    from ..warnings.anchors import invalidate
    ids = _normalized_ids(fiber_ids)
    probes = tuple(key for key in _CACHE if _scope_matches(key[0], scene, root, ids))
    for key in probes:
        _CACHE.pop(key, None)
    invalidate(scene, root, ids)
    _invalidate_overlay(None)


def clear_transient_fiber_attachment_statuses(root=None, fiber_ids=None):
    ids = _normalized_ids(fiber_ids)
    roots = (root,) if root is not None else _all_roots()
    for item in roots:
        _clear_root_statuses(item, ids)


def fiber_anchor_cache_stats():
    from ..warnings.session import REPOSITORY
    return {"entries": len(_CACHE), "current": len(REPOSITORY.metadata), "limit": _CACHE_LIMIT}


def _compute_preflight(root, scene, fiber, depsgraph, quality, probe, anchors):
    from .attachment_surface import support_keys
    oracle = CollisionOracle(root, scene, depsgraph, max(0.0, float(fiber.collision_radius)), 0.002, support_keys(fiber))
    sources = tuple(oracle.colliders())
    colliders = _capture_colliders(sources)
    slack = _clearance_slack(colliders, fiber.collision_radius, quality)
    hierarchy = _hierarchy(root)
    key = _full_key(probe, anchors, sources, hierarchy, slack)
    result = evaluate_anchor_preflight(anchors, colliders, hierarchy, fiber.collision_radius, slack, key)
    _store(probe, result)
    _publish(root, scene, fiber, result)
    return result


def _resolve_anchors(root, scene, fiber, solver, depsgraph):
    fn = solver._loop_anchors if is_loop_fiber(fiber) else solver._open_anchors
    _runtime, rows, issue = fn(root, scene, depsgraph, fiber)
    if issue or rows is None:
        return None, str(issue or "Invalid Fiber anchors.")
    return _hard_anchors(fiber, _authored_rows(fiber, rows)), ""


def _authored_rows(fiber, rows):
    values = tuple(rows or ())
    if not is_loop_fiber(fiber):
        return values
    count = len(tuple(getattr(fiber, "loop_anchors", ()) or ()))
    return values[:count]


def _hard_anchors(fiber, rows):
    values = tuple(rows or ())
    if is_loop_fiber(fiber):
        return tuple(_hard_anchor(row, V2AnchorRole.LOOP, index) for index, row in enumerate(values))
    last = len(values) - 1
    return tuple(_hard_anchor(row, _open_role(index, last), index) for index, row in enumerate(values))


def _hard_anchor(row, role, index):
    point = tuple(float(value) for value in row.point)
    return FiberHardAnchor(point, str(row.owner_id or ""), role, int(index))


def _open_role(index, last):
    if index == 0:
        return V2AnchorRole.ENDPOINT_A
    return V2AnchorRole.ENDPOINT_B if index == last else V2AnchorRole.TOUCH


def _capture_colliders(sources):
    from .fiber_v2_runtime import _capture_collider
    rows = tuple(_capture_collider(source, index) for index, source in enumerate(sources))
    return tuple(row for row in rows if row is not None)


def _clearance_slack(colliders, radius, quality):
    from .fiber_v2_runtime import _tolerances
    value = "FINAL" if str(quality).upper() == "FINAL" else "INTERACTIVE"
    from .v2.contracts import V2Quality
    return _tolerances(colliders, float(radius), V2Quality(value)).clearance_slack


def _collision_world(colliders, key):
    generation = ("hard-anchor", repr(tuple(key)))
    if native_batch_status():
        return cached_native_collision_world_batch(colliders, generation)
    return cached_native_collision_world(colliders, generation)


def _contact_pairs(world, anchors, threshold):
    points = np.asarray([row.point for row in anchors], dtype=np.float64)
    edges = np.asarray([(index, index) for index in range(len(anchors))], dtype=np.int64)
    owners = tuple(("", "") for _row in anchors)
    skips = tuple(row.owner_id for row in anchors)
    return world.contact_pairs(points, edges, owners, 0.0, threshold, skip=skips)


def _violations(anchors, colliders, hierarchy, configured, effective, pairs):
    owners = {str(row.collider_id): str(row.owner_id) for row in tuple(colliders or ())}
    values = (_violation(anchors, owners, hierarchy, configured, effective, pair) for pair in pairs)
    filtered = tuple(value for value in values if value is not None)
    deduped = _dedupe_violations(filtered)
    return tuple(sorted(deduped, key=_violation_sort_key))


def _violation(anchors, owners, hierarchy, configured, effective, pair):
    anchor = anchors[int(pair.edge)]
    blocker = owners.get(str(pair.collider_id), str(pair.collider_id))
    if blocker == anchor.owner_id:
        return None
    measured, contained = float(pair.distance), bool(pair.contained)
    if not contained and measured >= float(effective):
        return None
    relation = _relation(anchor.owner_id, blocker, hierarchy)
    residual = max(0.0, float(effective) - measured)
    action = _action(anchor.role, anchor.owner_id)
    return FiberAnchorViolation(anchor.role, anchor.authored_index, anchor.owner_id, blocker,
                                relation, anchor.point, measured, float(configured),
                                float(effective), residual, contained, action)


def _dedupe_violations(values):
    rows = {}
    for value in values:
        key = value.authored_index, value.blocker_id
        current = rows.get(key)
        if current is None or _violation_rank(value) < _violation_rank(current):
            rows[key] = value
    return tuple(rows.values())


def _violation_rank(value):
    return (0 if value.contained else 1, float(value.measured_clearance))


def _violation_sort_key(value):
    return value.authored_index, value.role.value, value.blocker_id


def _relation(owner, blocker, hierarchy):
    if blocker in _ancestors(owner, hierarchy):
        return "ANCESTOR"
    if owner in _ancestors(blocker, hierarchy):
        return "DESCENDANT"
    return "UNRELATED"


def _ancestors(owner, hierarchy):
    values, current = set(), str(owner or "")
    while current and current not in values:
        current = str(hierarchy.get(current, "") or "")
        if current:
            values.add(current)
    return values


def _action(role, owner):
    if role is V2AnchorRole.TOUCH:
        return f"Increase touch offset or re-author the anchor on {owner}."
    return f"Move or re-author the attachment on {owner}."


def _probe_key(root, scene, fiber):
    scope = fiber_anchor_scope(scene, root, fiber)
    raw = _raw_anchor_specs(fiber)
    colliders = _collider_probe_rows(root, scene) + _muscle_probe_rows(root, scene, fiber)
    radius = float(getattr(fiber, "collision_radius", 0.0))
    status = collision_backend_status()
    return (scope, str(getattr(fiber, "topology_mode", "OPEN")), raw, colliders,
            radius, _OWNER_CONTACT_MODE, _hierarchy_rows(root), status.version)


def _full_key(probe, anchors, sources, hierarchy, slack):
    points = tuple((row.role.value, row.authored_index, row.owner_id, row.point) for row in anchors)
    colliders = tuple(_source_key(row) for row in sources)
    effective = max(0.0, float(probe[4]) - float(slack))
    return probe[:2] + (points, colliders, float(probe[4]), effective,
                        _OWNER_CONTACT_MODE, tuple(sorted(hierarchy.items())), probe[-1])


def _raw_anchor_specs(fiber):
    from .shared_point_storage import endpoint_record
    if is_loop_fiber(fiber):
        return tuple((row.parent_id, row.attach_param) for row in fiber.loop_anchors)
    mids = tuple((row.parent_id, row.attach_param, float(row.normal_offset)) for row in fiber.mid_touches)
    ends = tuple((p.parent_id, p.attach_param, p.normal_offset) for p in (endpoint_record(fiber, "a"), endpoint_record(fiber, "b")))
    return ends[0], mids, ends[1]


def _collider_probe_rows(root, scene):
    rows = tuple(iter_geometry_mesh_scp_objects(scene, str(getattr(root, "name", ""))))
    values = ((_object_sid(obj), str(obj.name), _collider_stamp(obj)) for obj in rows)
    return tuple(sorted(values, key=lambda row: (row[0], row[1])))


def _source_key(source):
    obj = source["obj"]
    data = getattr(obj, "data", None)
    counts = len(getattr(data, "vertices", ())), len(getattr(data, "polygons", ()))
    return str(source.get("sid", "")), str(obj.name), _collider_stamp(obj), counts


def _object_sid(obj):
    return str(obj.get("af_scp_id", "") or "")


def _muscle_probe_rows(root, scene, fiber):
    from .attachment_surface import support_keys, resolve_object
    from .surface_reference import is_muscle
    targets = tuple(value for value in support_keys(fiber) if is_muscle(value))
    objects = tuple(resolve_object(root, scene, target) for target in targets)
    return tuple((key, obj.name, _collider_stamp(obj)) if obj else (key, '', ()) for key, obj in zip(targets, objects))


def _hierarchy(root):
    scps = getattr(getattr(root, "af_scp_system", None), "scps", ())
    return {str(row.id or ""): str(row.parent_id or "") for row in scps}


def _hierarchy_rows(root):
    return tuple(sorted(_hierarchy(root).items()))


def _store(probe, result):
    _CACHE[probe] = result
    _CACHE.move_to_end(probe)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)


def _publish(root, scene, fiber, result):
    from ..warnings.anchors import publish
    publish(scene, root, fiber, result)


def _invalidate_overlay(scopes):
    try:
        from ..visualization.fiber_anchor_overlay import invalidate_fiber_anchor_overlay
        invalidate_fiber_anchor_overlay(scopes)
    except (ImportError, RuntimeError):
        return


def _scope_matches(scope, scene, root, ids):
    from ..warnings.session import id_token
    if scene is not None and scope[1] != id_token(scene):
        return False
    if root is not None and scope[2] != id_token(root):
        return False
    return ids is None or scope[4] in ids


def _normalized_ids(values):
    if values is None:
        return None
    rows = (values,) if isinstance(values, str) else tuple(values)
    return {str(value) for value in rows if str(value or "")}


def _id_token(value):
    if value is None:
        return ("", 0)
    uid = int(getattr(value, "session_uid", 0) or 0)
    return type(value).__name__, uid or _pointer(value)


def _pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)


def _all_roots():
    try:
        import bpy
        return tuple(obj for scene in bpy.data.scenes for obj in scene.objects
                     if obj.get("anthroforge_root"))
    except (ImportError, AttributeError):
        return ()


def _clear_root_statuses(root, ids):
    from .runtime_state import (fiber_recompute_status, set_fiber_invalid_reason,
                                set_fiber_recompute_status)
    fibers = getattr(getattr(root, "af_vcp_system", None), "fibers", ())
    for fiber in fibers:
        if (ids is None or str(fiber.id) in ids) and fiber_recompute_status(fiber) == "INVALID_ATTACHMENT":
            set_fiber_invalid_reason(fiber, "")
            set_fiber_recompute_status(fiber, "UNKNOWN")
