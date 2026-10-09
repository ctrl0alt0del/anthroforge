"""Repeatable inspection cameras; render visibility is restored before export."""
import bpy
from mathutils import Vector


def configure(owner, scene):
    from anthroforge.core.vcp.attachment_surface import muscle_backed
    fibers = {f.id: f for f in owner.af_vcp_system.fibers}
    for obj in scene.objects:
        if obj.get('af_muscle_proxy'): obj.color = (.52,.11,.08,1)
        if obj.get('af_soft_tissue_proxy'): obj.color = (.91,.64,.27,1)
        if obj.get('af_fiber_surface_proxy'): obj.color = (.1,.35,.6,1)
        if obj.get('af_fiber_proxy'):
            fiber = fibers[obj['af_fiber_id']]; obj.color = (.05,.9,.55,1) if muscle_backed(fiber) else (.45,.12,.55,1)
    scene.render.engine = 'BLENDER_WORKBENCH'; scene.render.resolution_x = 1100; scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100; scene.display.shading.color_type = 'OBJECT'
    scene.display.shading.light = 'STUDIO'; scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True; scene.display.shading.background_type = 'WORLD'
    scene.world = scene.world or bpy.data.worlds.new('Attachment inspection world')
    scene.world.color = (.055,.055,.055); _camera(scene)


def _camera(scene):
    points = [o.matrix_world @ Vector(c) for o in scene.objects if o.type == 'MESH' for c in o.bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3))); center = (low+high)*.5
    data = bpy.data.cameras.new('Attachment inspection'); camera = bpy.data.objects.new('Attachment inspection', data)
    scene.collection.objects.link(camera); camera.location = center+Vector((1,-1.3,3.5))
    camera.rotation_euler = (center-camera.location).to_track_quat('-Z','Y').to_euler()
    data.type = 'ORTHO'; data.ortho_scale = max(high-low)*1.4; scene.camera = camera
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
                area.spaces.active.region_3d.view_location = center; area.spaces.active.region_3d.view_distance = data.ortho_scale*1.3


def render(scene, path, fibers=False):
    hidden = {o: o.hide_render for o in scene.objects}
    try:
        for obj in scene.objects:
            if obj.get('af_muscle_surface') == 'INFL': obj.hide_render = False
            if obj.get('af_fiber_surface_proxy') or obj.get('af_muscle_surface') == 'BASE': obj.hide_render = True
            if obj.get('af_soft_tissue_rest_proxy'): obj.hide_render = True
            if fibers and obj.get('af_soft_tissue_proxy'): obj.hide_render = True
        scene.render.filepath = str(path); bpy.ops.render.render(write_still=True)
    finally:
        for obj, value in hidden.items(): obj.hide_render = value
