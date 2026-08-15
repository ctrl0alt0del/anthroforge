"""Render a true Blender/Eevee left-right V1 versus Package 4 comparison."""

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for data in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(data):
            data.remove(item)


def _basis(record):
    visual = record["visual"]
    rows = [np.asarray(visual[key], dtype=np.float64) for key in ("v1", "v2_reference")]
    cloud = np.vstack(rows); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    return center, axes


def _transform(values, center, axes, shift):
    points = np.asarray(values, dtype=np.float64).reshape((-1, 3))
    transformed = (points - center) @ axes.T
    transformed[:, 0] += shift
    return transformed


def _material(name, color, emission=0.0):
    material = bpy.data.materials.new(name); material.diffuse_color = (*color, 1.0)
    material.use_nodes = True; shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = 0.72
    _set_emission(shader, color, emission)
    return material


def _set_emission(shader, color, strength):
    if strength <= 0.0 or "Emission Color" not in shader.inputs:
        return
    shader.inputs["Emission Color"].default_value = (*color, 1.0)
    shader.inputs["Emission Strength"].default_value = strength


def _mesh_object(name, triangles, center, axes, shift, material):
    values = _transform(triangles, center, axes, shift)
    faces = np.arange(len(values), dtype=np.int64).reshape((-1, 3))
    mesh = bpy.data.meshes.new(name); mesh.from_pydata(values.tolist(), [], faces.tolist())
    mesh.materials.append(material); obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj); return obj


def _curve(name, points, center, axes, shift, radius, material):
    values = _transform(points, center, axes, shift)
    data = bpy.data.curves.new(name, "CURVE"); data.dimensions = "3D"
    data.bevel_depth = radius; data.bevel_resolution = 3; data.resolution_u = 2
    spline = data.splines.new("POLY"); spline.points.add(len(values) - 1)
    for point, value in zip(spline.points, values):
        point.co = (*value, 1.0)
    data.materials.append(material); obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj); return obj


def _edge_curves(record, center, axes, shift, radius, safe, unsafe):
    points = record["visual"]["v1"]; violating = set(record["v1"]["validation"]["violating_edges"])
    for index, edge in enumerate(zip(points[:-1], points[1:])):
        material = unsafe if index in violating else safe
        _curve(f"V1_EDGE_{index}", edge, center, axes, shift, radius, material)


def _sphere(name, point, radius, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=radius, location=point)
    obj = bpy.context.object; obj.name = name; obj.data.materials.append(material)
    return obj


def _pins(record, center, axes, shift, radius, material):
    reference = record["v2"]["reference"]["points"]
    for order, index in enumerate(record["v2"]["pin_indices"]):
        point = _transform((reference[index],), center, axes, shift)[0]
        _sphere(f"PIN_{shift}_{order}", point, radius, material)


def _bounds(record, center, axes):
    triangles = np.asarray(record["visual"]["nearby_triangles"], dtype=np.float64)
    routes = np.vstack((record["visual"]["v1"], record["visual"]["v2_reference"]))
    values = np.vstack((_transform(triangles, center, axes, 0.0), _transform(routes, center, axes, 0.0)))
    return values.min(axis=0), values.max(axis=0)


def _camera(low, high, shift, output):
    width = high[0] - low[0]; total_width = width + shift
    height = high[1] - low[1]; center = (low + high) * 0.5
    camera_data = bpy.data.cameras.new("CAMERA"); camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(total_width, height * 2.195) * 1.16
    camera = bpy.data.objects.new("CAMERA", camera_data); bpy.context.collection.objects.link(camera)
    camera.location = (center[0], center[1], high[2] + max(total_width, height) * 1.2)
    camera.rotation_euler = (0, 0, 0)
    bpy.context.scene.camera = camera; _render_settings(output)


def _render_settings(output):
    scene = bpy.context.scene; scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1800; scene.render.resolution_y = 820; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"; scene.render.filepath = str(output)
    scene.render.film_transparent = False; scene.world.color = (0.008, 0.012, 0.02)
    scene.view_settings.look = "AgX - Medium High Contrast"


def _lights(low, high):
    center = (low + high) * 0.5; size = max(high - low)
    _area_light("KEY", center + (size, -size, size * 2), size * 4, 320)
    _area_light("FILL", center + (-size, size, size), size * 3, 180)


def _area_light(name, location, size, energy):
    data = bpy.data.lights.new(name, "AREA"); data.energy = energy; data.shape = "DISK"; data.size = size
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj); obj.location = location
    direction = Vector((0, 0, 0)) - obj.location; obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _build(record, output):
    _reset_scene(); center, axes = _basis(record); low, high = _bounds(record, center, axes)
    width = max(high[0] - low[0], 1.0e-4); shift = width * 1.25; radius = max(width * 0.008, 0.002)
    materials = _materials(); triangles = record["visual"]["nearby_triangles"]
    _mesh_object("MESH_V1", triangles, center, axes, -shift / 2, materials[0])
    _mesh_object("MESH_V2", triangles, center, axes, shift / 2, materials[0])
    _routes(record, center, axes, shift, radius, materials); _camera(low, high, shift, output); _lights(low, high)
    bpy.ops.render.render(write_still=True)


def _materials():
    mesh = _material("COLLIDERS", (0.10, 0.14, 0.20)); _transparent(mesh, 0.38)
    orange = _material("V1", (1.0, 0.42, 0.05), 0.15)
    red = _material("UNSAFE", (1.0, 0.03, 0.03), 0.25); green = _material("V2", (0.04, 1.0, 0.32), 0.2)
    cyan = _material("PINS", (0.0, 0.75, 1.0), 0.25)
    return mesh, orange, red, green, cyan


def _transparent(material, alpha):
    material.diffuse_color = (*material.diffuse_color[:3], alpha)
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Alpha"].default_value = alpha
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"


def _routes(record, center, axes, shift, radius, materials):
    _mesh, orange, red, green, cyan = materials
    _edge_curves(record, center, axes, -shift / 2, radius, orange, red)
    _curve("V2_REFERENCE", record["visual"]["v2_reference"], center, axes, shift / 2, radius * 0.55, green)
    _curve("V2_CORRIDOR", record["visual"]["v2_corridor"], center, axes, shift / 2, radius * 1.15, green)
    _pins(record, center, axes, -shift / 2, radius * 2.0, cyan)
    _pins(record, center, axes, shift / 2, radius * 2.0, cyan)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output)


main()
