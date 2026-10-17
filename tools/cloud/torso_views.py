"""CPU-rendered previews; presentation changes occur only after the debug copy is saved."""
import bpy
from mathutils import Vector


def camera(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    low = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
    high = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
    center = (low + high) / 2
    scale = max(high - low) * 1.2
    data = bpy.data.cameras.new('Cloud preview')
    view = bpy.data.objects.new('Cloud preview', data)
    bpy.context.scene.collection.objects.link(view)
    data.type = 'ORTHO'; data.ortho_scale = scale
    bpy.context.scene.camera = view
    return view, center, scale


def lighting(center, scale):
    bpy.context.scene.world.color = (.3, .3, .3)
    for index, offset in enumerate(((2, -2, 3), (-2, 2, 2))):
        data = bpy.data.lights.new('Preview light ' + str(index), 'AREA')
        light = bpy.data.objects.new(data.name, data)
        bpy.context.scene.collection.objects.link(light)
        light.location = center + Vector(offset) * scale
        light.rotation_euler = (center-light.location).to_track_quat('-Z', 'Y').to_euler()
        data.energy = 150 * scale * scale
        data.shape = 'DISK'; data.size = scale * 2


def render_views(obj, output):
    scene = bpy.context.scene
    for item in scene.objects:
        item.hide_render = item != obj
    view, center, scale = camera(obj)
    lighting(center, scale)
    scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 16
    scene.render.resolution_x = 640; scene.render.resolution_y = 800; scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    for name, direction in [('front', (-1,0,0)), ('back', (1,0,0)), ('side', (0,1,0)), ('oblique', (-1,-1,.25))]:
        view.location = center + Vector(direction).normalized() * scale * 3
        view.rotation_euler = (center-view.location).to_track_quat('-Z','Y').to_euler()
        scene.render.filepath = str(output / (name + '.png'))
        bpy.ops.render.render(write_still=True)
