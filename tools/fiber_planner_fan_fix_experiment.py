"""A/B render for the minimal Fiber planner fanning correction."""

import argparse
import json
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def _helpers():
    tools_dir = str(Path(__file__).resolve().parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import fiber_planner_sphere_experiment as sphere
    return sphere


def _fixture(sphere):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sphere._register_addon()
    return sphere._new_fixture()


def _fixed_config(sphere, collider):
    u, v = sphere._bases()[0]
    config = (0, u, v, 240, 37.5, 6)
    targets = sphere._anchors(u, v, 240, 37.5, 6)
    return config, [_nearest_mesh_point(collider, point) for point in targets]


def _nearest_mesh_point(collider, point):
    matrix = collider.matrix_world
    points = tuple(matrix @ vertex.co for vertex in collider.data.vertices)
    return min(points, key=lambda candidate: (candidate - point).length_squared).copy()


def _timed_plan(sphere, oracle, anchors, repeats=5):
    result, samples = None, []
    for _index in range(repeats):
        start = time.perf_counter()
        result = sphere._planner_result(oracle, anchors)
        samples.append((time.perf_counter() - start) * 1000.0)
    return result, samples


def _mesh_only(oracle):
    from anthroforge.core.vcp.fiber_collision import _mesh_shell_nodes
    margin = max(oracle.margin, oracle.clearance)
    oracle.shell_nodes = lambda collider, dense=False: tuple(
        _mesh_shell_nodes(collider, margin, dense))
    return oracle


def _new_oracle(sphere, root, scene):
    return sphere._oracle(root, scene)


def _surface_candidate(oracle, anchors):
    from anthroforge.core.vcp.fiber_planner import PlannerResult, ROADMAP
    collider = oracle.collider_by_id("SPHERE")
    routes = [_surface_segment(oracle, collider, anchors[i:i + 2])
              for i in range(len(anchors) - 1)]
    return PlannerResult(_merge_routes(routes), ROADMAP, ("SPHERE",))


def _surface_segment(oracle, collider, anchors):
    from anthroforge.core.vcp.fiber_collision import _collider_surface
    surface = _collider_surface(collider)
    indices = tuple(_nearest_vertex(surface, point) for point in anchors)
    route = oracle.surface_path("SPHERE", indices[0], indices[1])
    return _clearance_route(oracle, collider, route, anchors)


def _nearest_vertex(surface, point):
    verts = tuple(surface.get("verts_world", ()))
    return min(range(len(verts)), key=lambda index: (verts[index] - point).length_squared)


def _clearance_route(oracle, collider, route, anchors):
    points = [anchors[0].copy()]
    points.extend(_pushed(oracle, collider, point) for point in route)
    points.append(anchors[1].copy())
    return points


def _pushed(oracle, collider, point):
    from anthroforge.core.vcp.fiber_collision import _collider_bvh, _query_nearest, _world_normal
    hit = _query_nearest(_collider_bvh(collider), point)
    normal = _world_normal(collider, hit[1])
    return Vector(hit[0]) + normal * _surface_clearance(oracle, collider)


def _surface_clearance(oracle, collider):
    _ = collider
    return max(oracle.clearance, oracle.margin)


def _merge_routes(routes):
    out = []
    for index, route in enumerate(routes):
        out.extend(route[1:] if index else route)
    return out


def _timed_surface(oracle, anchors, repeats=5):
    result, samples = None, []
    for _index in range(repeats):
        start = time.perf_counter()
        result = _surface_candidate(oracle, anchors)
        samples.append((time.perf_counter() - start) * 1000.0)
    return result, samples


def _path_metrics(sphere, result, anchors, samples, safe):
    direct = sum((anchors[i + 1] - anchors[i]).length for i in range(len(anchors) - 1))
    route = sphere._route_length(result.points)
    return {"points": len(result.points), "route_length": route, "safe": bool(safe),
            "detour_ratio": route / direct, "timings_ms": samples,
            "median_ms": sorted(samples)[len(samples) // 2],
            "route": [list(point) for point in result.points]}


def _translate(points, offset):
    return [Vector(point) + Vector(offset) for point in points]


def _translated_sphere(source, offset):
    clone = source.copy()
    clone.data = source.data.copy()
    bpy.context.scene.collection.objects.link(clone)
    clone.location = offset
    clone.name = "Candidate_Sphere"
    return clone


def _comparison_visuals(sphere, collider, config, anchors, baseline, candidate):
    red = sphere._material("Current planner", (0.9, 0.01, 0.015, 1.0), 0.1, 0.2)
    green = sphere._material("Local surface candidate", (0.02, 0.85, 0.15, 1.0), 0.05, 0.2)
    cyan = sphere._material("Expected arc", (0.0, 0.65, 1.0, 1.0), 0.05, 0.2)
    orange = sphere._material("Anchors", (1.0, 0.42, 0.01, 1.0), 0.05, 0.2)
    _panel(sphere, config, anchors, baseline.points, (0, 0, 0), red, cyan, orange)
    _translated_sphere(collider, (5.2, 0, 0))
    _panel(sphere, config, anchors, candidate.points, (5.2, 0, 0), green, cyan, orange)


def _panel(sphere, config, anchors, route, offset, route_mat, arc_mat, anchor_mat):
    sphere._curve("Route", _translate(route, offset), route_mat, 0.028)
    arc = sphere._expected_arc(config[1], config[2], config[3], config[4])
    sphere._curve("Expected", _translate(arc, offset), arc_mat, 0.018)
    for index, point in enumerate(_translate(anchors, offset)):
        sphere._marker(f"Anchor_{offset[0]}_{index}", point * 1.0, anchor_mat, 0.055)


def _camera(sphere, baseline, candidate):
    points = tuple(baseline.points) + tuple(_translate(candidate.points, (5.2, 0, 0)))
    sphere._camera_for(points, None)
    bpy.context.scene.camera.data.ortho_scale = 8.8


def _render(sphere, scene, output):
    sphere._render_settings(scene, output)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix(".blend")))
    bpy.ops.render.render(write_still=True)


def _route_safe(oracle, points, anchors):
    return all(_chunk_safe(oracle, chunk) for chunk in _route_chunks(points, anchors))


def _route_chunks(points, anchors):
    starts = [_point_index(points, anchor) for anchor in anchors]
    return [points[starts[i]:starts[i + 1] + 1] for i in range(len(starts) - 1)]


def _point_index(points, target):
    return next(i for i, point in enumerate(points) if (point - target).length <= 1.0e-6)


def _chunk_safe(oracle, points):
    states = [_edge_state(oracle, points, i) for i in range(len(points) - 1)]
    if not all(states):
        print("UNSAFE_CHUNK=" + json.dumps({"points": [list(p) for p in points], "states": states}))
    return all(states)


def _edge_state(oracle, points, index):
    owners = ("SPHERE" if index == 0 else "",
              "SPHERE" if index + 2 == len(points) else "")
    result = _surface_edge_clear(oracle, points[index], points[index + 1], owners)
    if not result:
        _edge_diagnostic(oracle, points[index], points[index + 1], owners)
    return result


def _surface_edge_clear(oracle, a, b, owners):
    from anthroforge.core.vcp.fiber_collision import _trimmed_segment, _segment_ray_world_hit
    collider = oracle.collider_by_id("SPHERE")
    p0, p1 = _trimmed_segment(oracle, collider, a, b, owners)
    return p0 is None or (_segment_ray_world_hit(collider, p0, p1) is None and
                          _unsigned_samples_clear(oracle, collider, p0, p1))


def _unsigned_samples_clear(oracle, collider, a, b):
    from anthroforge.core.vcp.fiber_collision import _bvh_unsigned_distance
    return all(_bvh_unsigned_distance(collider, a.lerp(b, step / 8.0)) >= oracle.margin
               for step in range(1, 8))


def _edge_diagnostic(oracle, a, b, owners):
    from anthroforge.core.vcp.fiber_collision import _trimmed_segment, _segment_ray_world_hit, _sample_pen
    collider = oracle.collider_by_id("SPHERE")
    p0, p1 = _trimmed_segment(oracle, collider, a, b, owners)
    pens = [_sample_pen(collider, p0.lerp(p1, step / 6.0), oracle.margin) for step in range(1, 6)]
    report = {"owners": owners, "trimmed": [list(p0), list(p1)],
              "ray_hit": _segment_ray_world_hit(collider, p0, p1) is not None, "sample_pen": pens}
    print("UNSAFE_EDGE=" + json.dumps(report))


def _report(sphere, anchors, baseline, base_times, candidate, candidate_times, oracles):
    base = _path_metrics(sphere, baseline, anchors, base_times, _route_safe(oracles[0], baseline.points, anchors))
    fixed = _path_metrics(sphere, candidate, anchors, candidate_times, _route_safe(oracles[1], candidate.points, anchors))
    return {"baseline": base, "local_surface": fixed}


def _run_planners(sphere, root, scene, anchors):
    baseline_oracle = _new_oracle(sphere, root, scene)
    baseline, base_times = _timed_plan(sphere, baseline_oracle, anchors)
    candidate_oracle = _new_oracle(sphere, root, scene)
    candidate, candidate_times = _timed_surface(candidate_oracle, anchors)
    timings = base_times, candidate_times
    return baseline, candidate, timings, (baseline_oracle, candidate_oracle)


def main():
    args, sphere = _args(), _helpers()
    scene, root, collider = _fixture(sphere)
    config, anchors = _fixed_config(sphere, collider)
    baseline, candidate, timings, oracles = _run_planners(sphere, root, scene, anchors)
    report = _report(sphere, anchors, baseline, timings[0], candidate, timings[1], oracles)
    _comparison_visuals(sphere, collider, config, anchors, baseline, candidate)
    _camera(sphere, baseline, candidate)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _render(sphere, scene, output)
    print("FIBER_FAN_FIX_EXPERIMENT=" + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
