"""Render a true Blender V1 / Package 4 / Package 4.1 comparison."""

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True); parser.add_argument("--output", required=True)
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(values)


def _reset_scene():
    bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)
    groups = (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights)
    for group in groups:
        for item in list(group):
            group.remove(item)


def _basis(record):
    visual = record["visual"]
    rows = [np.asarray(visual[key], dtype=np.float64) for key in ("v1", "package4", "package41")]
    cloud = np.vstack(rows); center = cloud.mean(axis=0)
    _u, _s, axes = np.linalg.svd(cloud - center, full_matrices=False)
    return center, axes


def _transform(values, center, axes, shift):
    points = np.asarray(values, dtype=np.float64).reshape((-1, 3))
    output = (points - center) @ axes.T; output[:, 0] += shift
    return output


def _material(name, color, emission=0.0, alpha=1.0):
    material = bpy.data.materials.new(name); material.diffuse_color = (*color, alpha)
    material.use_nodes = True; shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0); shader.inputs["Roughness"].default_value = .72
    _shader_style(material, shader, color, emission, alpha); return material


def _shader_style(material, shader, color, emission, alpha):
    if "Emission Color" in shader.inputs:
        shader.inputs["Emission Color"].default_value = (*color, 1.0)
        shader.inputs["Emission Strength"].default_value = emission
    shader.inputs["Alpha"].default_value = alpha
    if alpha < 1.0 and hasattr(material, "surface_render_method"):
        material.surface_render_method = "DITHERED"


def _mesh(name, triangles, center, axes, shift, material):
    values = _transform(triangles, center, axes, shift)
    faces = np.arange(len(values), dtype=np.int64).reshape((-1, 3))
    data = bpy.data.meshes.new(name); data.from_pydata(values.tolist(), [], faces.tolist())
    data.materials.append(material); obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)


def _curve(name, points, center, axes, shift, radius, material):
    values = _transform(points, center, axes, shift); data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"; data.bevel_depth = radius; data.bevel_resolution = 3
    spline = data.splines.new("POLY"); spline.points.add(len(values) - 1)
    for point, value in zip(spline.points, values):
        point.co = (*value, 1.0)
    data.materials.append(material); obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)


def _v1_edges(record, center, axes, shift, radius, safe, unsafe):
    points = record["visual"]["v1"]; bad = set(record["v1"]["validation"]["violating_edges"])
    for index, edge in enumerate(zip(points[:-1], points[1:])):
        _curve(f"V1_{index}", edge, center, axes, shift, radius, unsafe if index in bad else safe)


def _routes(record, center, axes, shifts, radius, materials):
    _mesh_mat, orange, red, green, blue = materials
    _v1_edges(record, center, axes, shifts[0], radius, orange, red)
    _route_pair(record, "package4", center, axes, shifts[1], radius, green)
    _route_pair(record, "package41", center, axes, shifts[2], radius, blue)


def _route_pair(record, key, center, axes, shift, radius, material):
    points = record["visual"][key]
    _curve(f"{key}_REFERENCE", points, center, axes, shift, radius * .52, material)
    corridor = record[key]["route"]["points"]
    _curve(f"{key}_CORRIDOR", corridor, center, axes, shift, radius * 1.15, material)


def _bounds(record, center, axes):
    triangles = np.asarray(record["visual"]["nearby_triangles"], dtype=np.float64)
    routes = np.vstack([record["visual"][key] for key in ("v1", "package4", "package41")])
    values = np.vstack((_transform(triangles, center, axes, 0.0), _transform(routes, center, axes, 0.0)))
    return values.min(axis=0), values.max(axis=0)


def _camera(low, high, spread, output):
    width, height = high[0] - low[0], high[1] - low[1]; center = (low + high) * .5
    data = bpy.data.cameras.new("CAMERA"); data.type = "ORTHO"
    data.ortho_scale = max(width + 2 * spread, height * 2.95) * 1.12
    camera = bpy.data.objects.new("CAMERA", data); bpy.context.collection.objects.link(camera)
    camera.location = (center[0], center[1], high[2] + max(width + spread, height) * 1.2)
    bpy.context.scene.camera = camera; _render_settings(output)


def _render_settings(output):
    scene = bpy.context.scene; scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 2400; scene.render.resolution_y = 820; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"; scene.render.filepath = str(output)
    scene.world.color = (.008, .012, .02); scene.view_settings.look = "AgX - Medium High Contrast"


def _lights(low, high):
    center = (low + high) * .5; size = max(high - low)
    _light("KEY", center + (size, -size, 2 * size), 4 * size, 320)
    _light("FILL", center + (-size, size, size), 3 * size, 180)


def _light(name, location, size, energy):
    data = bpy.data.lights.new(name, "AREA"); data.energy = energy; data.size = size
    obj = bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj); obj.location = location
    obj.rotation_euler = (Vector((0, 0, 0)) - obj.location).to_track_quat("-Z", "Y").to_euler()


def _materials():
    mesh = _material("COLLIDERS", (.10, .14, .20), alpha=.38)
    orange = _material("V1", (1.0, .42, .05), .15); red = _material("UNSAFE", (1.0, .03, .03), .25)
    green = _material("P4", (.04, 1.0, .32), .2); blue = _material("P41", (.05, .58, 1.0), .25)
    return mesh, orange, red, green, blue


def _build(record, output):
    _reset_scene(); center, axes = _basis(record); low, high = _bounds(record, center, axes)
    width = max(high[0] - low[0], 1e-4); spread = width * 1.18; shifts = (-spread, 0.0, spread)
    radius = max(width * .008, .002); materials = _materials(); triangles = record["visual"]["nearby_triangles"]
    for index, shift in enumerate(shifts):
        _mesh(f"MESH_{index}", triangles, center, axes, shift, materials[0])
    _routes(record, center, axes, shifts, radius, materials); _camera(low, high, spread, output); _lights(low, high)
    bpy.ops.render.render(write_still=True)


def main():
    args = _arguments(); record = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    _build(record, output)


main()
