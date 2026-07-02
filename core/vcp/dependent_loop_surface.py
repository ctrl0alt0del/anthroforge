from math import ceil

from mathutils import Vector

from ..scp_runtime.common import find_geometry_mesh_scp_obj
from ..scp_runtime.surface import frame_from_parent_param, nearest_parent_param_from_world
from .fiber_loop import loop_plane, profile_offsets
from .fiber_modes import loop_anchor_specs


def reference_surface_parent_id(driver_fiber):
    ids = {pid for pid, _raw in loop_anchor_specs(driver_fiber) if pid}
    return next(iter(ids)) if len(ids) == 1 else ""


def surface_bias(offset_u, avg_step):
    step = max(float(avg_step), 1.0e-9)
    return max(0.0, min(1.0, abs(float(offset_u)) / step))


def surface_target_points(root, scene, depsgraph, driver_fiber, driver_points, fiber, runtime):
    parent_obj = _reference_surface_obj(root, scene, driver_fiber)
    cache = _surface_cache(runtime)
    nodes = _captured_nodes(parent_obj, driver_points, depsgraph, cache)
    if not nodes:
        return []
    avg_step = _avg_step(nodes)
    walked = walk_surface_offset(parent_obj, nodes, fiber, avg_step, depsgraph, cache)
    return fair_surface_loop(parent_obj, walked, fiber, avg_step, depsgraph, cache)


def walk_surface_offset(parent_obj, nodes, fiber, avg_step, depsgraph, cache):
    plan = _walk_plan(nodes, fiber, avg_step)
    moved = [dict(node) for node in tuple(nodes or ())]
    for step_index in range(_walk_pass_total(plan)):
        moved = _walk_pass(parent_obj, moved, plan, step_index, depsgraph, cache)
        if not moved:
            return []
    return moved


def fair_surface_loop(parent_obj, nodes, fiber, avg_step, depsgraph, cache):
    _ = fiber
    stable = [dict(node) for node in tuple(nodes or ())]
    for _index in range(_fair_pass_total(stable)):
        candidate = _fair_world_pass(parent_obj, stable, depsgraph, cache)
        if not _stable_nodes(candidate, avg_step):
            break
        stable = candidate
    return stable


def inward_tangent(point, normal, tangent, center):
    base = _safe_dir(normal.cross(tangent), center - point)
    return base if base.dot(center - point) >= 0.0 else -base


def _reference_surface_obj(root, scene, driver_fiber):
    parent_id = reference_surface_parent_id(driver_fiber)
    if not root or not scene or not parent_id:
        return None
    return find_geometry_mesh_scp_obj(scene, root.name, parent_id)


def _surface_cache(runtime):
    data = runtime if isinstance(runtime, dict) else {}
    return data.setdefault("surface_cache", {})


def _captured_nodes(parent_obj, points, depsgraph, cache):
    items = [_captured_node(parent_obj, point, depsgraph, cache) for point in tuple(points or ())]
    return [] if not items or any(node is None for node in items) else items


def _captured_node(parent_obj, world_point, depsgraph, cache, bias=0.0):
    param = None if parent_obj is None else nearest_parent_param_from_world(parent_obj, world_point, depsgraph, cache=cache)
    frame = None if param is None else frame_from_parent_param(parent_obj, param, depsgraph, cache=cache)
    if frame is None:
        return None
    return {"param": param, "point": frame["point_world"].copy(), "normal": frame["normal_world"].normalized(), "bias": float(bias)}


def _avg_step(nodes):
    if len(nodes) < 2:
        return 0.0
    lengths = [_edge_len(nodes, i) for i in range(len(nodes))]
    return sum(lengths) / float(len(lengths))


def _edge_len(nodes, index):
    a = nodes[index]["point"]
    b = nodes[(index + 1) % len(nodes)]["point"]
    return (b - a).length


def _loop_center(nodes):
    return sum((node["point"] for node in nodes), Vector()) / float(max(1, len(nodes)))


def _walk_plan(nodes, fiber, avg_step):
    count = len(nodes)
    return [_walk_item(fiber, avg_step, i, count) for i in range(count)]


def _walk_item(fiber, avg_step, index, count):
    offset_u, _offset_v = profile_offsets(fiber, index / float(max(1, count)))
    steps = _step_count(offset_u, avg_step)
    return {"step": float(offset_u) / float(max(1, steps)), "steps": steps, "bias": surface_bias(offset_u, avg_step)}


def _step_count(offset_u, avg_step):
    step = max(float(avg_step), 1.0e-9)
    return max(1, int(ceil(abs(float(offset_u)) / step)))


def _walk_pass_total(plan):
    return max((int(item["steps"]) for item in tuple(plan or ())), default=0)


def _walk_pass(parent_obj, nodes, plan, step_index, depsgraph, cache):
    center = _loop_center(nodes)
    points = [_walk_point(nodes, plan, center, i, step_index) for i in range(len(nodes))]
    return _recaptured_nodes(parent_obj, points, _biased_nodes(nodes, plan), depsgraph, cache)


def _walk_point(nodes, plan, center, index, step_index):
    item = plan[index]
    if step_index >= int(item["steps"]):
        return nodes[index]["point"].copy()
    prev_pt, next_pt = _neighbor_points(nodes, index)
    tangent = _loop_tangent(prev_pt, nodes[index]["point"], next_pt)
    delta = inward_tangent(nodes[index]["point"], nodes[index]["normal"], tangent, center) * float(item["step"])
    return nodes[index]["point"] + delta


def _neighbor_points(nodes, index):
    return nodes[index - 1]["point"], nodes[(index + 1) % len(nodes)]["point"]


def _biased_nodes(nodes, plan):
    return [dict(nodes[i], bias=float(plan[i]["bias"])) for i in range(len(nodes))]


def _loop_tangent(prev_pt, point, next_pt):
    return _safe_dir((next_pt - point) + (point - prev_pt), next_pt - prev_pt)


def _safe_dir(vector, fallback):
    return Vector(fallback).normalized() if Vector(vector).length <= 1.0e-8 else Vector(vector).normalized()


def _fair_pass_total(nodes):
    value = max((float(node.get("bias", 0.0)) for node in tuple(nodes or ())), default=0.0)
    return max(0, min(4, int(round(value * 4.0))))


def _fair_world_pass(parent_obj, nodes, depsgraph, cache):
    points = [_smoothed_point(nodes, i) for i in range(len(nodes))]
    return _recaptured_nodes(parent_obj, points, nodes, depsgraph, cache)


def _smoothed_point(nodes, index):
    prev_pt, cur_pt = nodes[index - 1]["point"], nodes[index]["point"]
    next_pt = nodes[(index + 1) % len(nodes)]["point"]
    return cur_pt.lerp((prev_pt + next_pt) * 0.5, 0.5)


def _recaptured_nodes(parent_obj, points, nodes, depsgraph, cache):
    items = [_captured_node(parent_obj, point, depsgraph, cache, nodes[i].get("bias", 0.0)) for i, point in enumerate(points)]
    return [] if not items or any(node is None for node in items) else items


def _stable_nodes(nodes, avg_step):
    points = [node["point"] for node in tuple(nodes or ())]
    return bool(points) and not _collapsed_loop(points, avg_step) and not _self_intersects(points)


def _collapsed_loop(points, avg_step):
    tol = max(1.0e-6, float(avg_step) * 0.05)
    return any((points[(i + 1) % len(points)] - points[i]).length <= tol for i in range(len(points)))


def _self_intersects(points):
    flat = _flat_points(points)
    return any(_cross_pair(flat, i, j) for i in range(len(flat)) for j in range(i + 1, len(flat)) if _separate_edges(i, j, len(flat)))


def _flat_points(points):
    origin, axis_u, axis_v, _normal = loop_plane(points)
    return [Vector(((point - origin).dot(axis_u), (point - origin).dot(axis_v))) for point in points]


def _separate_edges(i, j, count):
    return abs(i - j) > 1 and not (i == 0 and j == count - 1)


def _cross_pair(points, i, j):
    a0, a1 = points[i], points[(i + 1) % len(points)]
    b0, b1 = points[j], points[(j + 1) % len(points)]
    return _segments_cross(a0, a1, b0, b1)


def _segments_cross(a0, a1, b0, b1, eps=1.0e-6):
    o1, o2 = _orient2(a0, a1, b0), _orient2(a0, a1, b1)
    o3, o4 = _orient2(b0, b1, a0), _orient2(b0, b1, a1)
    return o1 * o2 < -eps and o3 * o4 < -eps


def _orient2(a, b, c):
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
