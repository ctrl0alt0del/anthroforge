"""Render a read-only production Fiber planner preview from a supplied blend."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--fiber", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def _load(path):
    tools_dir = str(Path(__file__).resolve().parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import fiber_perf_probe
    sync = fiber_perf_probe._load(path)
    scene = bpy.context.scene
    root = fiber_perf_probe._root(scene)
    return sync, scene, root


def _fiber(root, fiber_id):
    return next(item for item in root.af_vcp_system.fibers
                if item.id == fiber_id or item.name == fiber_id)


def _planner_data(root, scene, fiber):
    from anthroforge.core.vcp.fiber_planner import _plan_segment, _segments, plan_route
    from anthroforge.core.vcp.fiber_solver import FiberSolver
    solver, depsgraph = FiberSolver(), bpy.context.evaluated_depsgraph_get()
    _runtime, anchors, issue = solver._open_anchors(root, scene, depsgraph, fiber)
    params, oracle, context_issue = solver._solver_context(root, scene, fiber, anchors, depsgraph, False, False)
    if issue or context_issue:
        raise RuntimeError(issue or context_issue)
    segments = [_plan_segment(oracle, segment, False) for segment in _segments(anchors)]
    return anchors, plan_route(oracle, anchors, False), segments, oracle, params


def _proxy_points(scene, root, fiber_id):
    match = next((obj for obj in scene.objects if obj.get("af_fiber_proxy") and
                  not obj.get("af_fiber_mirror_proxy") and obj.get("af_root_name") == root.name and
                  obj.get("af_fiber_id") == fiber_id), None)
    return [] if match is None else [match.matrix_world @ Vector(point.co[:3])
                                    for spline in match.data.splines for point in spline.points]


def _path_length(points):
    return sum((points[index + 1] - points[index]).length for index in range(len(points) - 1))


def _turn_angles(points):
    values = []
    for index in range(1, len(points) - 1):
        first, second = points[index] - points[index - 1], points[index + 1] - points[index]
        if first.length > 1.0e-9 and second.length > 1.0e-9:
            values.append(math.degrees(first.angle(second)))
    return values


def _report(fiber, anchors, result, segments, persisted, params, oracle):
    angles = _turn_angles(result.points)
    direct = _path_length([anchor.point for anchor in anchors])
    return {"fiber": fiber.id, "mode": result.mode, "active_ids": result.active_ids,
            "settings": {key: params.get(key) for key in ("margin", "node_count", "iterations")},
            "anchors": [_anchor_row(anchor) for anchor in anchors],
            "segments": [_segment_row(item) for item in segments],
            "surface_candidates": _surface_candidates(oracle, anchors),
            "planner": _route_row(result.points, direct, angles),
            "persisted": _route_row(persisted, direct, _turn_angles(persisted))}


def _surface_candidates(oracle, anchors):
    from anthroforge.core.vcp.fiber_planner import _initial_colliders, _segments
    return [_surface_candidate(oracle, segment, _initial_colliders(oracle, segment))
            for segment in _segments(anchors)]


def _surface_candidate(oracle, segment, active):
    from anthroforge.core.vcp.fiber_planner import _surface_points, _surface_setup
    setup = _surface_setup(oracle, segment, active)
    if setup is None:
        return {"available": False}
    owner, params, colliders = setup
    raw = oracle.surface_param_path(owner, *params)
    points = _surface_points(segment, oracle.surface_local_path(owner, *params))
    visible = bool(points and oracle.surface_route_visible(points, owner, colliders))
    return _surface_candidate_row(oracle, segment, owner, colliders, raw, points, visible)


def _surface_candidate_row(oracle, segment, owner, colliders, raw, points, visible):
    from anthroforge.core.vcp.fiber_planner import _surface_quality_ok
    return {"available": True, "points": len(points), "length": _path_length(points),
            "quality": _surface_quality_ok(points, segment), "visible": visible,
            "active_ids": [item["sid"] for item in colliders],
            "failed_edges": _failed_surface_edges(oracle, owner, points, colliders),
            "owner_signed": _owner_signed_distances(oracle, owner, points),
            "dense_variants": _dense_variants(oracle, owner, segment, raw, colliders),
            "repair_variant": _repair_variant(oracle, owner, points, colliders),
            "normal_variants": _normal_variants(oracle, owner, segment, raw, colliders),
            "production_variants": _production_variants(oracle, owner, segment, colliders),
            "coordinates": [list(p) for p in points]}


def _production_variants(oracle, owner, segment, colliders):
    from anthroforge.core.vcp.fiber_planner import _surface_params, _surface_points
    params = _surface_params(segment)
    routes = () if params is None else oracle.surface_local_paths(owner, *params)
    return [_production_variant(oracle, owner, segment, route, colliders) for route in routes]


def _production_variant(oracle, owner, segment, route, colliders):
    from anthroforge.core.vcp.fiber_planner import _surface_points
    points = _surface_points(segment, route)
    points = oracle.surface_route_shortcut(points, owner, colliders)
    points = oracle.surface_route_relax(points, owner, colliders)
    return _shortcut_row(oracle, owner, points, colliders)


def _dense_variants(oracle, owner, segment, raw, colliders):
    from anthroforge.core.vcp.fiber_collision import _offset_surface_route
    values = []
    for factor in (2.0, 1.0, 0.5, 0.25):
        dense = _densify(raw, max(1.0e-5, oracle.clearance * factor))
        points = _surface_points_for(segment, _offset_surface_route(oracle, oracle.collider_by_id(owner), dense))
        values.append({"factor": factor, "points": len(points), "visible": oracle.surface_route_visible(points, owner, colliders),
                       "length": _path_length(points), "max_turn": max(_turn_angles(points), default=0.0)})
    return values


def _surface_points_for(segment, route):
    from anthroforge.core.vcp.fiber_planner import _surface_points
    return _surface_points(segment, route)


def _densify(points, max_step):
    out = [points[0].copy()]
    for start, end in zip(points[:-1], points[1:]):
        count = max(1, int(math.ceil((end - start).length / max_step)))
        out.extend(start.lerp(end, step / count) for step in range(1, count + 1))
    return out


def _repair_variant(oracle, owner_id, points, colliders):
    owner = oracle.collider_by_id(owner_id)
    repaired = _repair_route(oracle, owner, points)
    angles = _turn_angles(repaired)
    return {"points": len(repaired), "visible": oracle.surface_route_visible(repaired, owner_id, colliders),
            "length": _path_length(repaired), "max_turn": max(angles, default=0.0),
            "turns_over_30": sum(value > 30.0 for value in angles),
            "coordinates": [list(point) for point in repaired]}


def _repair_route(oracle, owner, points):
    out = [points[0].copy()]
    for index, (start, end) in enumerate(zip(points[:-1], points[1:])):
        owners = (owner["sid"] if index == 0 else "", owner["sid"] if index + 2 == len(points) else "")
        out.extend(_repair_edge(oracle, owner, start, end, owners, 8))
    return out


def _repair_edge(oracle, owner, start, end, owners, depth):
    from anthroforge.core.vcp.fiber_collision import _nearest_push, _surface_owner_clear
    if _surface_owner_clear(oracle, owner, start, end, owners) or depth <= 0:
        return [end.copy()]
    midpoint, _pen = _nearest_push(owner, start.lerp(end, 0.5), oracle.clearance)
    left = _repair_edge(oracle, owner, start, midpoint, (owners[0], ""), depth - 1)
    return left + _repair_edge(oracle, owner, midpoint, end, ("", owners[1]), depth - 1)


def _normal_variants(oracle, owner_id, segment, raw, colliders):
    return [_normal_variant(oracle, owner_id, segment, raw, colliders, factor)
            for factor in (1.0, 2.0, 2.5, 3.0, 3.5, 4.0)]


def _normal_variant(oracle, owner_id, segment, raw, colliders, factor):
    owner = oracle.collider_by_id(owner_id)
    points = _surface_points_for(segment, _normal_offset_route(oracle, owner, raw, factor))
    angles = _turn_angles(points)
    short = _surface_shortcut(oracle, owner_id, points, colliders)
    strict = _strict_route_visible(oracle, owner_id, points, colliders)
    return {"factor": factor, "points": len(points), "visible": oracle.surface_route_visible(points, owner_id, colliders),
            "strict_visible": strict,
            "length": _path_length(points), "max_turn": max(angles, default=0.0),
            "turns_over_30": sum(value > 30.0 for value in angles),
            "shortcut": _shortcut_row(oracle, owner_id, short, colliders),
            "relax": _relax_rows(oracle, owner_id, short, colliders),
            "coordinates": [list(point) for point in points]}


def _relax_rows(oracle, owner_id, points, colliders):
    return {str(count): _shortcut_row(oracle, owner_id, _relax_surface(
        oracle, owner_id, points, colliders, count), colliders) for count in (2, 4, 6, 8, 12)}


def _chaikin(points, rounds):
    out = [point.copy() for point in points]
    for _index in range(rounds):
        out = _chaikin_once(out)
    return out


def _chaikin_once(points):
    out = [points[0].copy()]
    for first, second in zip(points[:-1], points[1:]):
        out.extend((first.lerp(second, 0.25), first.lerp(second, 0.75)))
    out.append(points[-1].copy())
    return out


def _smooth_projected_route(oracle, collider, raw, factor):
    from anthroforge.core.vcp.fiber_collision import _collider_surface
    surface = _collider_surface(collider)
    normals = _vertex_normals(surface)
    smooth = _chaikin(raw, 2)[1:-1]
    return [_projected_offset(oracle, collider, surface, normals, point, factor) for point in smooth]


def _projected_offset(oracle, collider, surface, normals, point, factor):
    from anthroforge.core.vcp.fiber_collision import _choose_exterior_offset, _query_nearest
    hit = _query_nearest(surface["bvh_world"], point)
    if not hit or hit[0] is None:
        return point.copy()
    co, _normal, tri_index, _distance = hit
    direction = _hit_normal(surface, normals, tri_index, Vector(co))
    return _choose_exterior_offset(collider, Vector(co), direction, oracle.clearance * factor)


def _hit_normal(surface, normals, tri_index, point):
    from anthroforge.core.scp_runtime.surface import _closest_point_barycentric
    tri = surface["triangles"][int(tri_index)]
    abc = tuple(surface["verts_world"][index] for index in tri)
    weights = _closest_point_barycentric(*abc, point) or (1.0 / 3.0,) * 3
    normal = sum((normals[index] * weight for index, weight in zip(tri, weights)), Vector())
    return normal.normalized() if normal.length > 1.0e-9 else Vector((0.0, 0.0, 1.0))


def _chord_projected_route(oracle, owner, segment, factor, count=12):
    from anthroforge.core.vcp.fiber_collision import _collider_surface
    surface = _collider_surface(owner)
    normals = _vertex_normals(surface)
    samples = [segment.start.point.lerp(segment.end.point, index / count) for index in range(1, count)]
    return [_projected_offset(oracle, owner, surface, normals, point, factor) for point in samples]


def _surface_shortcut(oracle, owner_id, points, colliders):
    out, index = [points[0].copy()], 0
    while index < len(points) - 1:
        index = _furthest_surface_point(oracle, owner_id, points, colliders, index)
        out.append(points[index].copy())
    return out


def _relax_surface(oracle, owner_id, points, colliders, iterations=12):
    out = [point.copy() for point in points]
    for _iteration in range(iterations):
        for index in range(1, len(out) - 1):
            out[index] = _relaxed_point(oracle, owner_id, out, colliders, index)
    return out


def _relaxed_point(oracle, owner_id, points, colliders, index):
    target = (points[index - 1] + points[index + 1]) * 0.5
    for alpha in (0.5, 0.25, 0.125, 0.0625):
        candidate = points[index].lerp(target, alpha)
        if _relaxed_edges_clear(oracle, owner_id, points, colliders, index, candidate):
            return candidate
    return points[index].copy()


def _relaxed_edges_clear(oracle, owner_id, points, colliders, index, candidate):
    left = (owner_id if index == 1 else "", "")
    right = ("", owner_id if index + 2 == len(points) else "")
    return (_strict_edge_clear(oracle, points[index - 1], candidate, left, colliders) and
            _strict_edge_clear(oracle, candidate, points[index + 1], right, colliders))


def _furthest_surface_point(oracle, owner_id, points, colliders, index):
    for candidate in range(len(points) - 1, index, -1):
        owners = (owner_id if index == 0 else "", owner_id if candidate + 1 == len(points) else "")
        if _strict_edge_clear(oracle, points[index], points[candidate], owners, colliders):
            return candidate
    return index + 1


def _strict_route_visible(oracle, owner_id, points, colliders):
    for index in range(len(points) - 1):
        owners = (owner_id if index == 0 else "", owner_id if index + 2 == len(points) else "")
        if not _strict_edge_clear(oracle, points[index], points[index + 1], owners, colliders):
            return False
    return True


def _strict_edge_clear(oracle, start, end, owners, colliders):
    from anthroforge.core.vcp.fiber_collision import _segment_clear
    return all(_segment_clear(oracle, collider, start, end, owners) for collider in colliders)


def _shortcut_row(oracle, owner_id, points, colliders):
    angles = _turn_angles(points)
    return {"points": len(points), "visible": _strict_route_visible(oracle, owner_id, points, colliders),
            "length": _path_length(points), "max_turn": max(angles, default=0.0),
            "turns_over_30": sum(value > 30.0 for value in angles),
            "coordinates": [list(point) for point in points]}


def _normal_offset_route(oracle, collider, raw, factor):
    from anthroforge.core.vcp.fiber_collision import _collider_surface
    surface = _collider_surface(collider)
    normals = _vertex_normals(surface)
    return [_normal_offset_point(oracle, collider, surface, normals, point, factor) for point in raw]


def _vertex_normals(surface):
    verts, normals = surface["verts_world"], [Vector() for _ in surface["verts_world"]]
    for tri in surface["triangles"]:
        normal = (verts[tri[1]] - verts[tri[0]]).cross(verts[tri[2]] - verts[tri[0]])
        for index in tri:
            normals[index] += normal
    return [normal.normalized() if normal.length > 1.0e-9 else Vector((0, 0, 1)) for normal in normals]


def _normal_offset_point(oracle, collider, surface, normals, point, factor):
    from anthroforge.core.vcp.fiber_collision import _choose_exterior_offset, _offset_surface_point
    index = min(range(len(surface["verts_world"])), key=lambda item: (surface["verts_world"][item] - point).length_squared)
    if (surface["verts_world"][index] - point).length > 1.0e-6:
        return _offset_surface_point(oracle, collider, point)
    return _choose_exterior_offset(collider, point, normals[index], oracle.clearance * factor)


def _experimental_route(oracle, anchors):
    from anthroforge.core.vcp.fiber_planner import _segments
    paths = [_experimental_segment(oracle, segment) for segment in _segments(anchors)]
    return [point.copy() for index, path in enumerate(paths) for point in path[index > 0:]]


def _experimental_segment(oracle, segment):
    from anthroforge.core.vcp.fiber_planner import _initial_colliders, _surface_setup
    setup = _surface_setup(oracle, segment, _initial_colliders(oracle, segment))
    if setup is None:
        return [segment.start.point, segment.end.point]
    owner, params, colliders = setup
    raw = oracle.surface_param_path(owner, *params)
    candidates = _experimental_candidates(oracle, owner, segment, raw, colliders)
    return min(candidates, key=_path_length) if candidates else [segment.start.point, segment.end.point]


def _experimental_candidates(oracle, owner, segment, raw, colliders):
    out = []
    for factor in (1.0, 2.0, 2.5, 3.0, 3.5, 4.0):
        points = _surface_points_for(segment, _normal_offset_route(
            oracle, oracle.collider_by_id(owner), raw, factor))
        smooth = _relax_surface(oracle, owner, _surface_shortcut(
            oracle, owner, points, colliders), colliders, 6)
        active = oracle.active_colliders_for_polyline(smooth, padding=oracle.clearance * 2.0)
        if _strict_route_visible(oracle, owner, smooth, active):
            out.append(smooth)
    return out


def _failed_surface_edges(oracle, owner_id, points, colliders):
    from anthroforge.core.vcp.fiber_collision import _same_collider, _segment_clear, _surface_edge_owners, _surface_owner_clear
    owner = oracle.collider_by_id(owner_id)
    failures = []
    for index in range(len(points) - 1):
        owners = _surface_edge_owners(owner_id, index, len(points))
        failed = [item["sid"] for item in colliders if not
                  (_surface_owner_clear if _same_collider(item, owner) else _segment_clear)
                  (oracle, item, points[index], points[index + 1], owners)]
        failures.extend([] if not failed else [_edge_failure(oracle, owner, points, index, failed, owners)])
    return failures


def _owner_signed_distances(oracle, owner_id, points):
    from anthroforge.core.vcp.fiber_collision import _bvh_signed_distance
    collider = oracle.collider_by_id(owner_id)
    return [_bvh_signed_distance(collider, point) for point in points]


def _edge_failure(oracle, collider, points, index, failed, owners):
    from anthroforge.core.vcp.fiber_collision import _bvh_unsigned_distance, _segment_ray_world_hit, _trimmed_segment
    start, end = _trimmed_segment(oracle, collider, points[index], points[index + 1], owners)
    samples = [] if start is None else [start.lerp(end, step / 16.0) for step in range(17)]
    return {"edge": index, "colliders": failed,
            "owner_ray": False if start is None else _segment_ray_world_hit(collider, start, end) is not None,
            "owner_min_unsigned": min((_bvh_unsigned_distance(collider, point) for point in samples), default=1.0e9)}


def _anchor_row(anchor):
    return {"owner": anchor.owner_id, "point": list(anchor.point),
            "surface_param": "surface_param_v2" in str(anchor.attach_raw)}


def _segment_row(result):
    return {"mode": result.mode, "points": len(result.points),
            "length": _path_length(result.points), "active_ids": result.active_ids}


def _route_row(points, direct, angles):
    return {"points": len(points), "length": _path_length(points),
            "detour_ratio": _path_length(points) / max(direct, 1.0e-9),
            "max_turn_deg": max(angles, default=0.0),
            "turns_over_30": sum(value > 30.0 for value in angles),
            "coordinates": [list(point) for point in points]}


def _material(name, color):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    return material


def _curve(name, points, color, width):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions, data.bevel_depth, data.bevel_resolution = "3D", width, 3
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for item, point in zip(spline.points, points):
        item.co = (*point, 1.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(_material(name, color))
    return obj


def _marker(name, point, color, radius):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=radius, location=point)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(_material(name, color))
    return obj


def _is_active_mesh(obj, active_ids):
    return obj.type == "MESH" and str(obj.get("af_scp_id", "")) in active_ids


def _prepare_scene(scene, result, anchors, persisted):
    active = set(result.active_ids)
    for obj in scene.objects:
        obj.hide_render = not _is_active_mesh(obj, active)
    _curve("PLANNER_PREVIEW", result.points, (1.0, 0.025, 0.015), 0.006)
    _curve("PERSISTED_FIBER", persisted, (0.0, 0.65, 1.0), 0.0035) if persisted else None
    for index, anchor in enumerate(anchors):
        _marker(f"ANCHOR_{index}", anchor.point, (1.0, 0.55, 0.0), 0.012)
    return tuple(result.points) + tuple(anchor.point for anchor in anchors)


def _look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def _camera(scene, points, direction):
    center = sum((Vector(point) for point in points), Vector()) / len(points)
    radius = max((Vector(point) - center).length for point in points)
    data = bpy.data.cameras.new("PlannerCamera")
    camera = bpy.data.objects.new("PlannerCamera", data)
    scene.collection.objects.link(camera)
    camera.location, data.type, data.ortho_scale = center + direction.normalized() * max(1.0, radius * 5.0), "ORTHO", max(0.3, radius * 2.5)
    _look_at(camera, center)
    scene.camera = camera
    return camera


def _render(scene, output, points, name, direction):
    camera = _camera(scene, points, Vector(direction))
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light, scene.display.shading.color_type = "STUDIO", "MATERIAL"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1100, 850, 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output.with_name(f"{output.stem}_{name}.png"))
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)


def main():
    args = _args()
    _sync, scene, root = _load(args.blend)
    fiber = _fiber(root, args.fiber)
    anchors, result, segments, _oracle, params = _planner_data(root, scene, fiber)
    persisted = _proxy_points(scene, root, fiber.id)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(_report(fiber, anchors, result, segments, persisted, params, _oracle), indent=2), encoding="utf-8")
    points = _prepare_scene(scene, result, anchors, persisted)
    for name, direction in (("iso", (1, -1, 0.7)), ("front", (0, -1, 0)), ("side", (1, 0, 0)), ("top", (0, 0, 1))):
        _render(scene, output, points, name, direction)
    print("AF_FIBER_CAPTURE=" + str(output.with_suffix(".json")))


if __name__ == "__main__":
    main()
