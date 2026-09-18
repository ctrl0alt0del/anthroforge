"""Capture and resolve Fiber nodes through the existing SCP surface attachment model."""

from dataclasses import dataclass, replace
from math import isfinite
from time import perf_counter

from mathutils import Vector

from ..scp_runtime.common import iter_geometry_mesh_scp_objects, instance_geometry_objects
from .attachment_backend import (attachment_runtime, capture_surface_param,
                                 resolve_attachment_normal, resolve_attachment_world,
                                 resolve_surface_frame)
from .fiber_collision import CollisionOracle
from .fiber_modes import fiber_parent_ids, is_loop_fiber, loop_anchor_specs
from .fiber_node_attachment_codec import (FiberNodeAttachment, FiberNodeAttachmentPayload,
                                          NODE_ATTACHMENT_VERSION, decode_node_attachments,
                                          encode_node_attachments, FiberNodeInfluence, node_influences)
from .fiber_node_attachment_weights import attachment_owner_weights
from .prop_update_guard import suppress_vcp_prop_updates


@dataclass(frozen=True)
class FiberNodeAttachmentResult:
    ok: bool
    points: tuple = ()
    error: str = ""
    elapsed_ms: float = 0.0


def capture_fiber_node_attachments(root, scene, fiber, points, depsgraph=None):
    started = perf_counter(); rows = tuple(Vector(point) for point in points)
    payload, error = _capture_payload(root, scene, fiber, rows, depsgraph)
    with suppress_vcp_prop_updates():
        fiber.node_attachments_json = "" if payload is None else encode_node_attachments(payload)
    return FiberNodeAttachmentResult(payload is not None, rows, error, _elapsed(started))


def resolve_fiber_node_attachments(root, scene, fiber, runtime=None):
    started = perf_counter(); payload = decode_node_attachments(fiber.node_attachments_json)
    error = _payload_issue(payload, fiber)
    if error: return FiberNodeAttachmentResult(False, error=error, elapsed_ms=_elapsed(started))
    runtime = runtime or attachment_runtime(scene)
    objects = runtime.get('node_attachment_objects')
    if objects is None: objects = _surface_objects(scene, root)
    points = tuple(_resolve_node(row, objects, runtime, scene) for row in payload.nodes)
    error = _resolved_issue(points)
    return FiberNodeAttachmentResult(not error, points if not error else (), error, _elapsed(started))


def clear_fiber_node_attachments(fiber):
    with suppress_vcp_prop_updates():
        fiber.node_attachments_json = ""


def _capture_payload(root, scene, fiber, points, depsgraph):
    if len(points) < 2: return None, "Fiber has no committed nodes."
    runtime = attachment_runtime(scene, depsgraph)
    objects = _candidate_objects(root, scene, fiber, points, runtime)
    if not objects: return None, "No SCP geometry surface is available."
    forced = _forced_nodes(root, scene, fiber, points, runtime)
    nodes = tuple(_capture_node(point, forced.get(index), objects, runtime, scene)
                  for index, point in enumerate(points))
    if any(row is None for row in nodes): return None, "A Fiber node could not attach to an SCP surface."
    nodes = _blend_nodes(points, nodes, forced, objects, runtime, scene, is_loop_fiber(fiber))
    if nodes is None: return None, "A blended Fiber attachment frame could not be captured."
    return FiberNodeAttachmentPayload(NODE_ATTACHMENT_VERSION, len(nodes),
                                      is_loop_fiber(fiber), nodes), ""


def _surface_objects(scene, root):
    values = tuple(iter_geometry_mesh_scp_objects(scene, root.name))
    objects = {str(obj.get("af_scp_id", "") or ""): obj for obj in values
               if str(obj.get("af_scp_id", "") or "")}
    objects.update(instance_geometry_objects(scene, root.name))
    return objects


def _candidate_objects(root, scene, fiber, points, runtime):
    objects = _surface_objects(scene, root)
    wanted = _nearby_surface_ids(root, scene, fiber, points, runtime)
    wanted.update(str(value or "") for value in fiber_parent_ids(fiber))
    selected = {key: value for key, value in objects.items() if key in wanted}
    return selected or objects


def _nearby_surface_ids(root, scene, fiber, points, runtime):
    radius = float(getattr(fiber, "collision_radius", 0.002))
    try:
        oracle = CollisionOracle(root, scene, runtime.get("depsgraph"), radius, 0.0)
        active = oracle.active_colliders_for_polyline(points, padding=max(0.01, radius * 8.0))
    except Exception:
        active = ()
    return {str(row.get("sid", "") or "") for row in active}


def _capture_node(point, forced, objects, runtime, scene):
    if forced is not None:
        return _node_from_raw(point, forced[0], forced[1], objects, runtime, scene)
    nearest = _nearest_node(point, objects, runtime, scene)
    return None if nearest is None else nearest[1]


def _nearest_node(point, objects, runtime, scene):
    rows = (_node_from_object(point, sid, obj, runtime, scene) for sid, obj in objects.items())
    values = tuple(row for row in rows if row is not None)
    return None if not values else min(values, key=lambda row: (row[0], row[1].target_id))


def _node_from_object(point, sid, obj, runtime, scene):
    raw = capture_surface_param(obj, point, runtime, scene)
    node = None if raw is None else _node_from_raw(point, sid, raw, {sid: obj}, runtime, scene)
    return None if node is None else (Vector(node.offset_local).length, node)


def _node_from_raw(point, sid, raw, objects, runtime, scene):
    frame = resolve_surface_frame(objects.get(str(sid or "")), raw, runtime, scene)
    if frame is None: return None
    offset = frame["basis_world"].inverted() @ (Vector(point) - frame["point_world"])
    return FiberNodeAttachment(str(sid or ""), str(raw or ""), tuple(offset))


def _forced_nodes(root, scene, fiber, points, runtime):
    specs = _anchor_specs(root, scene, fiber, runtime)
    anchors = tuple(row[2] for row in specs)
    indices = _pin_indices(points, anchors, is_loop_fiber(fiber))
    return {index: (row[0], row[1]) for index, row in zip(indices, specs)}


def _anchor_specs(root, scene, fiber, runtime):
    from .shared_point_storage import endpoint_record
    if is_loop_fiber(fiber): return _loop_specs(root, scene, fiber, runtime)
    first = _touch_spec(root, scene, runtime, endpoint_record(fiber, "a"))
    mids = tuple(_touch_spec(root, scene, runtime, row) for row in fiber.mid_touches)
    last = _touch_spec(root, scene, runtime, endpoint_record(fiber, "b"))
    return tuple(row for row in (first, *mids, last) if row is not None)


def _loop_specs(root, scene, fiber, runtime):
    rows = (_anchor_spec(root, scene, runtime, sid, raw) for sid, raw in loop_anchor_specs(fiber))
    return tuple(row for row in rows if row is not None)


def _anchor_spec(root, scene, runtime, sid, raw):
    point = resolve_attachment_world(root, scene, sid, raw, runtime)
    return None if point is None else (str(sid or ""), str(raw or ""), point)


def _touch_spec(root, scene, runtime, touch):
    point = resolve_attachment_world(root, scene, touch.parent_id, touch.attach_param, runtime)
    normal = resolve_attachment_normal(root, scene, touch.parent_id, touch.attach_param, runtime)
    if point is None or normal is None: return None
    point = point + normal * float(getattr(touch, "normal_offset", 0.0))
    return str(touch.parent_id or ""), str(touch.attach_param or ""), point


def _pin_indices(points, anchors, cyclic):
    if not anchors: return ()
    return _loop_pin_indices(points, anchors) if cyclic else _open_pin_indices(points, anchors)


def _open_pin_indices(points, anchors):
    if len(anchors) <= 1: return (0,)
    rows, cursor = [0], 1
    for offset, anchor in enumerate(anchors[1:-1], 1):
        stop = max(cursor + 1, len(points) - (len(anchors) - offset - 1))
        index = min(range(cursor, stop), key=lambda value: (points[value] - anchor).length_squared)
        rows.append(index); cursor = index + 1
    return tuple(rows + [len(points) - 1])


def _loop_pin_indices(points, anchors):
    first = min(range(len(points)), key=lambda value: (points[value] - anchors[0]).length_squared)
    rows, cursor = [first], first + 1
    for anchor in anchors[1:]:
        choices = range(cursor, cursor + len(points) - len(rows))
        chosen = min(choices, key=lambda value: (points[value % len(points)] - anchor).length_squared)
        rows.append(chosen % len(points)); cursor = chosen + 1
    return tuple(rows)


def _payload_issue(payload, fiber):
    if payload is None: return "Fiber node attachments are missing or invalid."
    if payload.point_count != int(getattr(fiber, "node_count", 0)): return "Fiber node count changed."
    if payload.cyclic != is_loop_fiber(fiber): return "Fiber topology changed."
    return ""


def _resolve_node(node, objects, runtime, scene):
    points = tuple((_resolve_influence(row, objects, runtime, scene), row.weight) for row in node_influences(node))
    if any(point is None for point, _weight in points): return None
    return sum((point * weight for point, weight in points), Vector())


def _resolve_influence(node, objects, runtime, scene):
    frame = resolve_surface_frame(objects.get(node.target_id), node.attach_raw, runtime, scene)
    return None if frame is None else frame["point_world"] + frame["basis_world"] @ Vector(node.offset_local)


def _blend_nodes(points, nodes, pins, objects, runtime, scene, cyclic):
    try: weights = attachment_owner_weights(points, [row.target_id for row in nodes], pins, cyclic)
    except ValueError: return None
    values = tuple(_blend_node(point, node, row, objects, runtime, scene)
                   for point, node, row in zip(points, nodes, weights))
    return values if all(row is not None for row in values) else None


def _blend_node(point, node, weights, objects, runtime, scene):
    if weights == ((node.target_id, 1.0),): return node
    influences = []
    for sid, weight in weights:
        binding = node if sid == node.target_id else _secondary_node(point, sid, objects, runtime, scene)
        if binding is None: return None
        influences.append(FiberNodeInfluence(sid, binding.attach_raw, binding.offset_local, weight))
    return replace(node, influences=tuple(influences))


def _secondary_node(point, sid, objects, runtime, scene):
    obj = objects.get(sid)
    if obj is None: return None
    row = _node_from_object(point, sid, obj, runtime, scene)
    return None if row is None else row[1]


def upgrade_fiber_node_attachments(root, scene, fiber, depsgraph=None):
    payload = decode_node_attachments(fiber.node_attachments_json)
    if payload is None or payload.version != 1 or _payload_issue(payload, fiber): return False
    runtime = attachment_runtime(scene, depsgraph); resolved = resolve_fiber_node_attachments(root, scene, fiber, runtime)
    if not resolved.ok: return False
    points = resolved.points; pins = _forced_nodes(root, scene, fiber, points, runtime)
    nodes = _blend_nodes(points, payload.nodes, pins, _surface_objects(scene, root), runtime, scene, payload.cyclic)
    if nodes is None: return False
    with suppress_vcp_prop_updates():
        fiber.node_attachments_json = encode_node_attachments(replace(payload, version=NODE_ATTACHMENT_VERSION, nodes=nodes))
    return True


def _resolved_issue(points):
    if any(point is None for point in points): return "A Fiber node attachment no longer resolves."
    finite = all(all(isfinite(float(value)) for value in point) for point in points)
    return "" if finite else "A Fiber node attachment produced non-finite coordinates."


def _elapsed(started):
    return (perf_counter() - started) * 1000.0
