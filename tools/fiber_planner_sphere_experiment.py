"""Reproduce and render Fiber planner fanning on a simple sphere collider."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def _args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])


def _register_addon():
    addon_dir = str(Path(__file__).resolve().parents[1])
    if str(Path(addon_dir).parent) not in sys.path:
        sys.path.insert(0, str(Path(addon_dir).parent))
    import anthroforge
    anthroforge.register()


def _new_fixture():
    from anthroforge.core.utils import ensure_af_root
    scene = bpy.context.scene
    root = ensure_af_root(scene)
    collider = _new_sphere(root)
    scene.view_layers[0].update()
    return scene, root, collider


def _new_sphere(root):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=2.0)
    sphere = bpy.context.object
    sphere.name = "Planner_Test_Sphere"
    _tag_collider(sphere, root.name)
    sphere.data.materials.append(_material("Sphere", (0.28, 0.08, 0.38, 1.0), 0.15, 0.55))
    return sphere


def _tag_collider(obj, root_name):
    obj["af_root_name"] = root_name
    obj["af_scp_id"] = "SPHERE"
    obj["af_scp_bound"] = True
    obj["af_scp_geometry"] = True


def _material(name, color, metallic=0.0, roughness=0.4):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.metallic = metallic
    mat.roughness = roughness
    return mat


def _bases():
    values = ((1, 0, 0, 0, 1, 0), (1, 0, 0, 0, 0, 1),
              (0, 1, 0, 0, 0, 1), (1, 1, 0, -1, 1, 1),
              (1, 0, 1, 0, 1, 0), (0, 1, 1, 1, 0, 0))
    return [(_normal(v[:3]), _orthogonal(v[:3], v[3:])) for v in values]


def _normal(values):
    return Vector(values).normalized()


def _orthogonal(first, second):
    u, raw = _normal(first), Vector(second)
    return (raw - u * raw.dot(u)).normalized()


def _anchors(u, v, center_deg, span_deg, count):
    first = math.radians(center_deg - span_deg * 0.5)
    step = math.radians(span_deg / float(count - 1))
    return [_sphere_point(u, v, first + step * i) for i in range(count)]


def _sphere_point(u, v, angle):
    return (u * math.cos(angle) + v * math.sin(angle)) * 2.0


def _planner_result(oracle, anchors):
    from anthroforge.core.vcp.fiber_planner import PlannerAnchor, plan_route
    authored = [PlannerAnchor(point, "SPHERE") for point in anchors]
    return plan_route(oracle, authored, allow_dense=False)


def _segment_results(oracle, anchors):
    return [_planner_result(oracle, anchors[i:i + 2]) for i in range(len(anchors) - 1)]


def _route_length(points):
    return sum((points[i + 1] - points[i]).length for i in range(len(points) - 1))


def _interior_points(results):
    return [point for result in results for point in result.points[1:-1]]


def _shared_waypoint(results, tolerance=1.0e-4):
    points = _interior_points(results)
    if not points:
        return None, 0
    best = max(points, key=lambda p: _waypoint_uses(p, results, tolerance))
    return best.copy(), _waypoint_uses(best, results, tolerance)


def _waypoint_uses(point, results, tolerance):
    return sum(any((candidate - point).length <= tolerance for candidate in result.points[1:-1])
               for result in results)


def _fan_score(anchors, results):
    waypoint, uses = _shared_waypoint(results)
    direct = sum((anchors[i + 1] - anchors[i]).length for i in range(len(anchors) - 1))
    routed = sum(_route_length(result.points) for result in results)
    radial = 0.0 if waypoint is None else max(0.0, waypoint.length - 2.0)
    return uses * 100.0 + radial * 25.0 + routed / max(direct, 1.0e-9)


def _configurations():
    for base_index, (u, v) in enumerate(_bases()):
        for center in range(0, 360, 15):
            for span, count in ((12, 4), (16, 5), (20, 5), (24, 6), (30, 6)):
                yield base_index, u, v, center, span, count


def _search(oracle):
    best = None
    for config in _configurations():
        anchors = _anchors(config[1], config[2], config[3], config[4], config[5])
        results = _segment_results(oracle, anchors)
        candidate = (_fan_score(anchors, results), config, anchors, results)
        best = candidate if best is None or candidate[0] > best[0] else best
    return best


def _curve(name, points, material, width):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions, data.bevel_depth, data.bevel_resolution = "3D", width, 3
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for item, point in zip(spline.points, points):
        item.co = (*point, 1.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def _expected_arc(u, v, center, span, samples=80):
    first = math.radians(center - span * 0.5)
    step = math.radians(span / float(samples - 1))
    return [_sphere_point(u, v, first + step * i) * 1.012 for i in range(samples)]


def _marker(name, point, material, radius):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=radius, location=point)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def _build_visuals(config, anchors, result, waypoint):
    red = _material("Planner preview", (0.85, 0.015, 0.02, 1.0), 0.1, 0.25)
    cyan = _material("Authored arc", (0.0, 0.8, 1.0, 1.0), 0.05, 0.2)
    yellow = _material("Anchors", (1.0, 0.45, 0.015, 1.0), 0.05, 0.2)
    _curve("PLANNER_PREVIEW", result.points, red, 0.028)
    _curve("EXPECTED_LOCAL_ARC", _expected_arc(config[1], config[2], config[3], config[4]), cyan, 0.018)
    for index, point in enumerate(anchors):
        _marker(f"Anchor_{index}", point * 1.012, yellow, 0.055)
    if waypoint is not None:
        _marker("Shared_distant_waypoint", waypoint, red, 0.075)


def _look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def _camera_for(points, waypoint):
    center = sum((Vector(p) for p in points), Vector()) / len(points)
    focus = center if waypoint is None else (center + waypoint) * 0.5
    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = focus + Vector((6.8, -7.5, 5.3))
    camera_data.type, camera_data.ortho_scale = "ORTHO", _view_scale(points, waypoint)
    _look_at(camera, focus)
    bpy.context.scene.camera = camera


def _view_scale(points, waypoint):
    values = [Vector(p) for p in points] + ([] if waypoint is None else [Vector(waypoint)])
    center = sum(values, Vector()) / len(values)
    return max(4.8, max((point - center).length for point in values) * 2.6)


def _lights():
    _light("Key", (4.5, -5.0, 6.0), 900.0, 5.0)
    _light("Fill", (-4.0, -1.0, 2.0), 650.0, 4.0)
    _light("Rim", (0.0, 5.0, 4.0), 750.0, 3.0)


def _light(name, location, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    _look_at(obj, (0.0, 0.0, 0.0))


def _render_settings(scene, output):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 1280, 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    scene.world = scene.world or bpy.data.worlds.new("World")
    scene.world.color = (0.018, 0.018, 0.025)


def _metrics(config, anchors, results, result, score):
    waypoint, uses = _shared_waypoint(results)
    direct = sum((anchors[i + 1] - anchors[i]).length for i in range(len(anchors) - 1))
    return {"score": score, "base": config[0], "center_deg": config[3],
            "span_deg": config[4], "anchor_count": config[5], "waypoint_uses": uses,
            "direct_length": direct, "route_length": _route_length(result.points),
            "detour_ratio": _route_length(result.points) / direct,
            "waypoint": None if waypoint is None else list(waypoint),
            "anchors": [list(point) for point in anchors],
            "planner_points": [list(point) for point in result.points]}


def _save(scene, output, metrics):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix(".blend")))
    bpy.ops.render.render(write_still=True)


def _oracle(root, scene):
    from anthroforge.core.vcp.fiber_collision import CollisionOracle
    graph = scene.view_layers[0].depsgraph
    return CollisionOracle(root, scene, graph, margin=0.02, surface_offset=0.02)


def _best_route(oracle):
    score, config, anchors, results = _search(oracle)
    return score, config, anchors, results, _planner_result(oracle, anchors)


def main():
    args = _args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _register_addon()
    scene, root, _collider = _new_fixture()
    oracle = _oracle(root, scene)
    score, config, anchors, results, result = _best_route(oracle)
    waypoint, _uses = _shared_waypoint(results)
    _build_visuals(config, anchors, result, waypoint)
    _camera_for((*anchors, *result.points), waypoint)
    _lights()
    output = Path(args.output).resolve()
    _render_settings(scene, output)
    metrics = _metrics(config, anchors, results, result, score)
    _save(scene, output, metrics)
    print("FIBER_SPHERE_EXPERIMENT=" + json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
