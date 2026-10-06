"""Read-only, cooperative capture using the production attachment/collision seams."""
from ..warnings import session
from ..warnings.anchors import identity, publish
from ..vcp import fiber_anchor_preflight as preflight
from ..vcp.attachment_backend import attachment_runtime, attachment_issue
from ..vcp.fiber_modes import is_loop_fiber
from .fiber_sync_helpers import endpoint_world, touch_world


def capture_colliders(scene, root, depsgraph, result, objects=None):
    from ..vcp.fiber_collision import _build_collider_entry
    from ..vcp.fiber_v2_runtime import _capture_collider, _CAPTURE_CACHE, _capture_key
    from ..scp_runtime.common import iter_geometry_mesh_scp_objects
    for obj in iter_geometry_mesh_scp_objects(scene, root.name) if objects is None else objects:
        source = session.measure("collider_bounds", _build_collider_entry, obj, scene, depsgraph)
        hit = source is not None and _capture_key(source, len(result)) in _CAPTURE_CACHE
        value = None if source is None else session.measure("collider_capture", _capture_collider, source, len(result))
        if value is None:
            raise ValueError(f"Cannot capture collider {obj.name}")
        result.append(value)
        session.COORDINATOR.metrics["capture_cache_hits"] += int(hit)
        session.COORDINATOR.metrics["captures"] += 1
        yield


def pin_specs(fiber):
    if is_loop_fiber(fiber):
        for index, pin in enumerate(fiber.loop_anchors):
            yield "LOOP", index, pin.parent_id, pin.attach_param, None
        return
    yield "ENDPOINT_A", 0, fiber.a_parent_id, fiber.a_attach_param, None
    for index, pin in enumerate(fiber.mid_touches):
        yield "TOUCH", index + 1, pin.parent_id, pin.attach_param, pin
    yield "ENDPOINT_B", len(fiber.mid_touches) + 1, fiber.b_parent_id, fiber.b_attach_param, None


def capture_pin(scene, root, runtime, spec):
    from ..vcp.v2.contracts import V2AnchorRole
    role, index, owner, raw, touch = spec
    if not owner_in_scope(scene, root, owner, runtime):
        raise ValueError(f"Missing or ambiguous parent geometry: {owner}")
    point = endpoint_world(root, scene, runtime, owner, raw) if touch is None else touch_world(root, scene, runtime, touch)
    if point is None:
        raise ValueError(attachment_issue(root, scene, owner, raw, runtime) or "Unresolved attachment")
    return preflight.FiberHardAnchor(tuple(float(v) for v in point), str(owner), V2AnchorRole(role), index)


def owner_in_scope(scene, root, owner, runtime=None):
    if runtime is not None and 'geometry_by_owner' in runtime:
        return len(runtime['geometry_by_owner'].get(str(owner), ())) == 1
    from ..scp_runtime.common import iter_geometry_mesh_scp_objects
    rows = [obj for obj in iter_geometry_mesh_scp_objects(scene, root.name)
            if str(obj.get("af_scp_id", "")) == str(owner) and not obj.get("af_scp_mirror")]
    return len(rows) == 1


def check_fiber(scene, root, fiber, colliders, world, runtime, generation, valid):
    ref, signature = identity(scene, root, fiber)
    session.REPOSITORY.state(ref.scope, "CHECKING", generation)
    try:
        result = yield from evaluate_fiber(scene, root, fiber, colliders, world, runtime)
        current_ref, current_signature = identity(scene, root, fiber)
        if valid() and current_ref.scope == ref.scope and current_signature == signature:
            publish(scene, root, fiber, result, generation)
            session.COORDINATOR.metrics["checked_entities"] += 1
        else:
            session.COORDINATOR.metrics["stale_rejects"] += 1
            session.REPOSITORY.state(ref.scope, "PENDING", generation)
    except (ValueError, RuntimeError, ReferenceError) as error:
        session.REPOSITORY.state(ref.scope, "FAILED", generation, error)
        session.COORDINATOR.metrics["failures"] += 1


def evaluate_fiber(scene, root, fiber, colliders, world, runtime):
    anchors, parts = [], []
    for spec in pin_specs(fiber):
        anchors.append(session.measure("pin_capture", capture_pin, scene, root, runtime, spec))
        yield
    slack = preflight._clearance_slack(colliders, fiber.collision_radius, "FINAL")
    hierarchy = preflight._hierarchy(root)
    for offset in range(0, len(anchors), 32):
        parts.append(session.measure("collision_batch", preflight.evaluate_anchor_preflight, anchors[offset:offset + 32], colliders,
                     hierarchy, fiber.collision_radius, slack, world=world))
        session.COORDINATOR.metrics["checked_pins"] += len(anchors[offset:offset + 32])
        yield
    violations = tuple(row for part in parts for row in part.violations)
    key = ("diagnostic", session.EPOCH, session.COORDINATOR.metrics["checked_pins"])
    return preflight.FiberAnchorPreflightResult(not violations, violations, key, sum(p.candidate_pairs for p in parts), sum(p.tested_pairs for p in parts), tuple(anchors))


def capture_root(scene, root):
    from ..utils import view_layer_for_scene
    layer = view_layer_for_scene(scene)
    if layer is None or layer.depsgraph is None:
        raise ValueError("Evaluated geometry is not ready")
    runtime = attachment_runtime(scene, layer.depsgraph)
    runtime.update(geometry_index(scene, root))
    return layer.depsgraph, runtime


def geometry_index(scene, root):
    from ..scp_runtime.common import iter_geometry_mesh_scp_objects
    objects = tuple(iter_geometry_mesh_scp_objects(scene, root.name))
    owners = {}
    for obj in objects:
        if not obj.get('af_scp_mirror'): owners.setdefault(str(obj.get('af_scp_id', '')), []).append(obj)
    return dict(geometry_objects=objects, geometry_by_owner=owners)
