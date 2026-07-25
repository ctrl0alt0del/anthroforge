import argparse
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meshes", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--variants", required=True)
    parser.add_argument("--heatmaps", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def is_source(obj):
    if obj.type != "MESH" or obj.get("af_draft_skin"):
        return False
    if obj.get("af_scp_geometry") or obj.get("af_blob_proxy"):
        return True
    return obj.get("af_muscle_surface") == "INFL"


def make_material(name, color, metallic=0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = 0.48
    shader.inputs["Metallic"].default_value = metallic
    return material


def assign_material(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)


def source_material(obj, bone, muscle, blob):
    if obj.get("af_blob_proxy"):
        return blob
    if obj.get("af_muscle_surface") == "INFL":
        return muscle
    return bone


def prepare_sources(materials):
    for obj in bpy.data.objects:
        obj.hide_render = True
    sources = [obj for obj in bpy.data.objects if is_source(obj)]
    for obj in sources:
        obj.hide_render = False
        assign_material(obj, source_material(obj, *materials))
    return sources


def add_mesh(name, path, material):
    data = np.load(path)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(data["vertices"].tolist(), [], data["faces"].tolist())
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    if "collagen" in data:
        add_collagen_colors(mesh, data["collagen"])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    assign_material(obj, material)
    return obj


def collagen_colors(values):
    values = np.clip(values, 0.0, 1.0)
    red = np.clip(2.0 * values, 0.0, 1.0)
    green = 1.0 - np.abs(2.0 * values - 1.0)
    blue = np.clip(2.0 * (1.0 - values), 0.0, 1.0)
    return np.column_stack((red, green, blue, np.ones_like(values)))


def add_collagen_colors(mesh, values):
    attribute = mesh.color_attributes.new(name="af_collagen", type="FLOAT_COLOR", domain="POINT")
    attribute.data.foreach_set("color", collagen_colors(values).ravel())


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_camera():
    data = bpy.data.cameras.new("AF_PROBE_CAMERA")
    camera = bpy.data.objects.new("AF_PROBE_CAMERA", data)
    bpy.context.scene.collection.objects.link(camera)
    data.type = "ORTHO"
    data.ortho_scale = 3.35
    bpy.context.scene.camera = camera
    return camera


def add_area(name, location, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    light = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(light)
    light.location = location
    look_at(light, (0.0, 0.0, 1.3))
    return light


def setup_lighting():
    add_area("Key", (-4.0, -5.0, 6.0), 1100.0, 4.0)
    add_area("Fill", (4.0, -3.0, 3.5), 750.0, 3.0)
    add_area("Rim", (0.0, 4.0, 5.0), 1000.0, 3.0)


def setup_scene(output):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.filepath = str(output)
    scene.view_settings.look = "AgX - Medium High Contrast"


def field_material():
    material = make_material("Collagen Field", (1.0, 1.0, 1.0))
    attribute = material.node_tree.nodes.new("ShaderNodeVertexColor")
    attribute.layer_name = "af_collagen"
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(attribute.outputs["Color"], shader.inputs["Base Color"])
    return material


def render_view(camera, output, location):
    camera.location = location
    look_at(camera, (0.0, 0.0, 1.31))
    bpy.context.scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)


def views():
    return {
        "front": (0.0, -8.0, 1.31),
        "threequarter": (5.0, -7.0, 3.0),
        "side": (8.0, 0.0, 1.31),
    }


def render_object_set(camera, folder, prefix):
    for name, location in views().items():
        render_view(camera, folder / f"{prefix}_{name}.png", location)


def hide_sources(sources, hidden):
    for obj in sources:
        obj.hide_render = hidden


def remove_object(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)


def render_variants(args, camera, sources, materials):
    folder = Path(args.output)
    hide_sources(sources, True)
    for name in args.variants.split(","):
        obj = add_mesh(f"AF_PROBE_{name}", Path(args.meshes) / f"{name}.npz", materials[0])
        render_object_set(camera, folder, name)
        render_heatmap(args, camera, folder, name, obj, materials[1])
        remove_object(obj)


def render_heatmap(args, camera, folder, name, obj, material):
    if not args.heatmaps:
        return
    assign_material(obj, material)
    render_object_set(camera, folder, f"{name}_field")


def main(args):
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    materials = make_material("Bone", (0.66, 0.52, 0.28)), make_material("Muscle", (0.52, 0.035, 0.02)), make_material("Blob", (0.8, 0.18, 0.03))
    sources = prepare_sources(materials)
    camera = add_camera()
    setup_lighting()
    setup_scene(folder)
    render_object_set(camera, folder, "structure")
    skin = make_material("Probe Skin", (0.12, 0.48, 0.82), 0.05)
    render_variants(args, camera, sources, (skin, field_material()))


if __name__ == "__main__":
    main(parse_args())
