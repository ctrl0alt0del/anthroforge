"""Render a real-collider left/right comparison of native legacy and indexed CCD."""

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("--input", required=True)
    parser.add_argument("--fiber", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", default=""); parser.add_argument("--controller", action="store_true")
    parser.add_argument("--view", choices=("plane", "depth"), default="plane")
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _ensure_addon():
    if hasattr(bpy.types.Object, "af_vcp_system"): return
    import anthroforge; anthroforge.register()


def _root(scene):
    return next(obj for obj in scene.objects if obj.get("anthroforge_root") and hasattr(obj, "af_vcp_system"))


def _fiber(root, name):
    key = name.upper(); return next(row for row in root.af_vcp_system.fibers
                                    if row.id.upper() == key or row.name.upper() == key)


def _request(root, scene, fiber):
    from anthroforge.core.visualization.fiber_refinement import _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request
    runtime = _prepared_session(root, scene, fiber, "FINAL")
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: raise RuntimeError(runtime.invalid_reason or runtime.runtime_error)
    value = _request(runtime); runtime.cancel(); return value


def _record(path, fiber):
    payload = json.loads(Path(path).read_text(encoding="utf-8")); key = fiber.upper()
    return next(row for row in payload["fibers"] if row["fiber"].upper() == key)


def _production_comparison(record, baseline):
    if not baseline: return record
    output = dict(record); output["points"] = dict(record["points"])
    output["points"]["native_legacy"] = baseline["points"]["current"]
    output["points"]["native_indexed"] = record["points"]["current"]
    output["labels"] = ("OLD PRODUCTION", "INDEXED PRODUCTION"); return output


def _controller_comparison(record):
    output = dict(record); output["points"] = dict(record["points"])
    output["points"]["native_legacy"] = record["points"]["current"]
    output["points"]["native_indexed"] = record["points"]["production_controller"]
    output["labels"] = ("PYTHON SQP", "NATIVE C++"); return output


def _basis(record):
    routes = np.vstack((record["points"]["native_legacy"], record["points"]["native_indexed"]))
    center = routes.mean(axis=0); _u, _s, axes = np.linalg.svd(routes - center, full_matrices=False)
    return center, axes, routes


def _nearby(collider, low, high, padding):
    vertices = np.asarray(collider.vertices); c_low, c_high = vertices.min(axis=0), vertices.max(axis=0)
    return bool(np.all(c_high >= low - padding) and np.all(c_low <= high + padding))


def _colliders(request, routes):
    low, high = routes.min(axis=0), routes.max(axis=0); extent = max(float(np.max(high - low)), 1.0e-4)
    padding = max(.2 * extent, 10.0 * request.collision_policy.collision_radius)
    return tuple(row for row in request.colliders if _nearby(row, low, high, padding))


def _reset():
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    for group in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for row in list(group): group.remove(row)


def _material(name, color, alpha=1.0, emission=0.0):
    material = bpy.data.materials.new(name); material.diffuse_color = (*color, alpha); material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF"); shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = .72; shader.inputs["Alpha"].default_value = alpha
    if "Emission Color" in shader.inputs: shader.inputs["Emission Color"].default_value = (*color, 1)
    if "Emission Strength" in shader.inputs: shader.inputs["Emission Strength"].default_value = emission
    if alpha < 1.0 and hasattr(material, "surface_render_method"): material.surface_render_method = "DITHERED"
    return material


def _world(scene):
    world = bpy.data.worlds.new("AF_COMPARE_WORLD"); world.use_nodes = True; scene.world = world
    shader = world.node_tree.nodes.get("Background")
    shader.inputs["Color"].default_value = (.018, .022, .032, 1.0)
    shader.inputs["Strength"].default_value = .35


def _transform(points, center, axes, shift):
    values = (np.asarray(points, dtype=np.float64) - center) @ axes.T; values[:, 0] += shift
    return values


def _mesh(name, collider, center, axes, shift, material):
    vertices = _transform(collider.vertices, center, axes, shift); faces = np.asarray(collider.triangles)
    data = bpy.data.meshes.new(name); data.from_pydata(vertices.tolist(), [], faces.tolist()); data.materials.append(material)
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj); return obj


def _curve(name, points, center, axes, shift, radius, material):
    values = _transform(points, center, axes, shift); data = bpy.data.curves.new(name, "CURVE")
    data.dimensions, data.bevel_depth, data.bevel_resolution = "3D", radius, 3
    spline = data.splines.new("POLY"); spline.points.add(len(values) - 1)
    for row, value in zip(spline.points, values): row.co = (*value, 1.0)
    data.materials.append(material); obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj); return obj


def _label(text, location, scale, view):
    data = bpy.data.curves.new(text, "FONT"); data.body = text; data.align_x = "CENTER"; data.size = scale
    obj = bpy.data.objects.new(text, data); bpy.context.collection.objects.link(obj); obj.location = location
    if view == "depth": obj.rotation_euler[0] = math.pi / 2.0
    data.materials.append(_material(text, (.9, .92, 1.0), emission=2.0)); return obj


def _build(record, request, center, axes, routes, view):
    local = (routes - center) @ axes.T; width = max(float(np.ptp(local[:, 0])), 1.0e-3)
    height = max(float(np.ptp(local[:, 1])), 1.0e-3); depth = max(float(np.ptp(local[:, 2])), 1.0e-3)
    shift = 1.45 * width; radius = .006 * max(width, height, depth)
    mesh_material = _material("COLLIDERS", (.3, .35, .45), .16, .22)
    legacy = _material("LEGACY", (0.0, .85, 1.0), emission=3.0); indexed = _material("INDEXED", (1.0, .05, .72), emission=3.0)
    for side in (-1, 1):
        for index, collider in enumerate(_colliders(request, routes)): _mesh(f"C_{side}_{index}", collider, center, axes, side * shift / 2, mesh_material)
    _curve("LEGACY_CCD", record["points"]["native_legacy"], center, axes, -shift / 2, radius, legacy)
    _curve("INDEXED_CCD", record["points"]["native_indexed"], center, axes, shift / 2, radius, indexed)
    labels = record.get("labels", ("LEGACY CCD", "INDEXED CCD"))
    label_z = .65 * depth if view == "depth" else .55 * height
    label_y = -.55 * height if view == "depth" else .65 * height
    _label(labels[0], (-shift / 2, label_y, label_z), .07 * max(height, depth), view)
    _label(labels[1], (shift / 2, label_y, label_z), .07 * max(height, depth), view)
    return width, height, depth, shift


def _render(output, dimensions, view):
    width, height, depth, shift = dimensions; data = bpy.data.cameras.new("CAMERA"); data.type = "ORTHO"
    vertical = depth if view == "depth" else height; data.ortho_scale = 1.7 * max(vertical, (width + shift) / 2.0)
    camera = bpy.data.objects.new("CAMERA", data); bpy.context.collection.objects.link(camera)
    distance = 5.0 * max(width, height, depth); camera.location = (0, -distance, 0) if view == "depth" else (0, 0, distance)
    camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera
    scene = bpy.context.scene; scene.render.engine = "BLENDER_EEVEE"; scene.render.resolution_x, scene.render.resolution_y = 1800, 900
    scene.render.resolution_percentage = 100; scene.render.image_settings.file_format = "PNG"; scene.render.filepath = str(output)
    _world(scene); scene.view_settings.look = "AgX - Medium High Contrast"; bpy.ops.render.render(write_still=True)


def main():
    args = _args(); _ensure_addon(); scene = bpy.context.scene; root = _root(scene)
    request = _request(root, scene, _fiber(root, args.fiber)); record = _record(args.input, args.fiber)
    baseline = _record(args.baseline, args.fiber) if args.baseline else None
    record = _production_comparison(record, baseline)
    if args.controller: record = _controller_comparison(record)
    center, axes, routes = _basis(record); output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _reset(); dimensions = _build(record, request, center, axes, routes, args.view); _render(output, dimensions, args.view)
    bpy.ops.wm.save_as_mainfile(filepath=str(output.with_suffix(".blend"))); print("AF_V3_SQP_RENDER=" + str(output))


if __name__ == "__main__":
    main()
