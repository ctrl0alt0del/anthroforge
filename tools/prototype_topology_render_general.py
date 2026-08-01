import argparse
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-dir", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def scene_objects():
    objects = tuple(bpy.context.scene.objects)
    skin = next(obj for obj in objects if obj.get("af_draft_skin"))
    topology = next(obj for obj in objects if obj.name == "AF_INSTANT_STITCHED")
    wire = next(obj for obj in objects if obj.name.startswith("AF_INSTANT_STITCHED_WIRE"))
    structure = tuple(obj for obj in objects if obj.get("af_scp_geometry"))
    return structure, skin, topology, wire


def material(name, color, emission=0.0):
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1.0)
    node.inputs["Roughness"].default_value = 0.6
    node.inputs["Emission Color"].default_value = (*color, 1.0)
    node.inputs["Emission Strength"].default_value = emission
    return value


def assign_material(objects, value):
    for obj in objects:
        if not hasattr(obj.data, "materials"):
            continue
        obj.data.materials.clear()
        obj.data.materials.append(value)


def world_bounds(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    values = np.asarray(points, dtype=np.float64)
    return values.min(axis=0), values.max(axis=0)


def make_camera(center, scale):
    data = bpy.data.cameras.new("AF_GENERAL_CAMERA")
    data.type = "ORTHO"
    data.ortho_scale = scale
    obj = bpy.data.objects.new("AF_GENERAL_CAMERA", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.scene.camera = obj
    return obj


def point_camera(camera, center):
    direction = Vector(center) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_light(name, center, offset, energy, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(center) + Vector(offset)
    bpy.context.scene.collection.objects.link(obj)
    point_camera(obj, center)


def configure_scene(center, diagonal):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.006, 0.009, 0.016)
    add_light("AF_GENERAL_KEY", center, (-diagonal, -diagonal, diagonal), 1800.0, diagonal)
    add_light("AF_GENERAL_FILL", center, (diagonal, -0.5 * diagonal, 0.2 * diagonal), 1000.0, diagonal)


def set_visible(visible):
    selected = set(visible)
    for obj in bpy.context.scene.objects:
        obj.hide_render = obj not in selected and obj.type not in {"CAMERA", "LIGHT"}


def view_position(center, diagonal, direction):
    vector = Vector(direction).normalized() * (1.8 * diagonal)
    return Vector(center) + vector


def render_panel(camera, center, diagonal, direction, visible, path):
    set_visible(visible)
    camera.location = view_position(center, diagonal, direction)
    point_camera(camera, center)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_views(folder, camera, center, diagonal, groups):
    views = (("along_x", (-1.0, 0.0, 0.0)), ("along_y", (0.0, -1.0, 0.0)),
             ("threequarter", (0.7, -1.0, 0.18)))
    for group_name, objects in groups.items():
        for view_name, direction in views:
            path = folder / f"{group_name}_{view_name}.png"
            render_panel(camera, center, diagonal, direction, objects, path)


def contact_sheet(folder):
    from PIL import Image, ImageDraw
    names = ("structure", "skin", "topology")
    images = [Image.open(folder / f"{name}_{view}.png") for view in ("front", "threequarter") for name in names]
    canvas = Image.new("RGB", (2700, 1800), (5, 8, 14))
    draw = ImageDraw.Draw(canvas)
    for index, image in enumerate(images):
        canvas.paste(image, ((index % 3) * 900, (index // 3) * 900))
        draw.text(((index % 3) * 900 + 16, (index // 3) * 900 + 16), names[index % 3], fill="white")
    canvas.save(folder / "skeleton_topology_comparison.png")


def prepare_groups():
    structure, skin, topology, wire = scene_objects()
    assign_material(structure, material("AF_GENERAL_STRUCTURE", (0.72, 0.56, 0.35)))
    assign_material((skin,), material("AF_GENERAL_SKIN", (0.72, 0.22, 0.48)))
    assign_material((topology,), material("AF_GENERAL_TOPOLOGY", (0.16, 0.35, 0.52)))
    assign_material((wire,), material("AF_GENERAL_WIRE", (0.1, 0.95, 1.0), 2.0))
    return structure, skin, topology, wire


def main():
    folder = Path(parse_args().render_dir)
    folder.mkdir(parents=True, exist_ok=True)
    structure, skin, topology, wire = prepare_groups()
    lower, upper = world_bounds((skin,))
    center, diagonal = 0.5 * (lower + upper), float(np.linalg.norm(upper - lower))
    configure_scene(center, diagonal)
    camera = make_camera(center, 1.05 * float((upper - lower)[2]))
    render_views(folder, camera, center, diagonal, {"structure": structure, "skin": (skin,), "topology": (topology, wire)})


if __name__ == "__main__":
    main()
