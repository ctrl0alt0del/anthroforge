"""Inspectable exact polylines and matched Blender renders from qualification JSON."""

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_v3_native_sqp_render as render


def arguments():
    parser = argparse.ArgumentParser(); parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--fiber', required=True)
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def request_for(data):
    colliders = tuple(SimpleNamespace(**row) for row in data['colliders'])
    return SimpleNamespace(colliders=colliders, collision_policy=SimpleNamespace(collision_radius=data['radius']))


def comparison(data, seed=False):
    rows = {row['mode']: row for row in data['results']}
    before = rows['INTEGRATED']['plan']['reference'] if seed else rows['BASE']['result']['points']
    return dict(points=dict(native_legacy=before, native_indexed=rows['INTEGRATED']['result']['points']),
        labels=('EXPANDED PLANNER', 'INTEGRATED SOLVER') if seed else ('WITHOUT RECOVERY', 'INTEGRATED RECOVERY'))


def camera_view(record, request, output, view):
    center, axes, routes = render._basis(record); bpy.ops.wm.read_factory_settings(use_empty=True)
    dimensions = render._build(record, request, center, axes, routes, view)
    comparison_labels(dimensions, view)
    comparison_camera(dimensions, view)
    render_comparison(output)


def comparison_labels(dimensions, view):
    width, height, depth, _shift = dimensions
    for obj in bpy.context.scene.objects:
        if obj.type != 'FONT': continue
        obj.data.size = .03*width
        if view == 'depth': obj.location.z = max(.8*depth, .15*width)
        else: obj.location.y = max(.8*height, .15*width)


def comparison_camera(dimensions, view):
    from mathutils import Vector
    width, height, depth, shift = dimensions; vertical = depth if view == 'depth' else height
    data = bpy.data.cameras.new('Comparison Camera'); data.type = 'ORTHO'
    data.ortho_scale = 1.2*max(width+shift, 2*vertical)
    camera = bpy.data.objects.new(data.name, data); bpy.context.collection.objects.link(camera)
    distance = 5*max(width, height, depth)
    camera.location = (0, -distance, 0) if view == 'depth' else (0, 0, distance)
    camera.rotation_euler = (Vector((0, 0, 0))-camera.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = camera


def render_comparison(output):
    scene = bpy.context.scene; scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = 1800, 900
    scene.render.resolution_percentage = 100; scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(output); render._world(scene)
    scene.view_settings.look = 'AgX - Medium High Contrast'
    bpy.ops.render.render(write_still=True)


def collection(name):
    result = bpy.data.collections.new(name); bpy.context.scene.collection.children.link(result)
    return result


def move_to(obj, target):
    for previous in tuple(obj.users_collection): previous.objects.unlink(obj)
    target.objects.link(obj)


def inspection(data, identifier, destination):
    bpy.ops.wm.read_factory_settings(use_empty=True); identity = np.eye(3); center = np.zeros(3)
    bones = collection('01 - Hand surfaces'); material = render._material('Bone', (.5, .55, .65))
    for row in request_for(data).colliders:
        move_to(render._mesh(row.collider_id, row, center, identity, 0., material), bones)
    for row in data['results']: inspection_paths(row, identifier, data['radius'], center, identity)
    scene = bpy.context.scene; scene['inspection_only'] = True
    scene['note'] = 'Exact world-space polylines; toggle collections to compare. Source blend unchanged.'
    set_inspection_view(comparison(data)['points']['native_indexed'])
    bpy.ops.wm.save_as_mainfile(filepath=str(destination))
    save_planner_copy(identifier, destination)


def save_planner_copy(identifier, destination):
    for group in bpy.data.collections:
        if not group.name.startswith(identifier): continue
        group.hide_viewport = group.hide_render = not group.name.endswith('INTEGRATED - PLANNER')
    path = destination.with_name(f'{identifier}_planner.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)


def inspection_paths(row, identifier, radius, center, identity):
    color = (.95, .05, .2) if row['mode'] == 'INTEGRATED' else (.05, .75, .95)
    material = render._material(row['mode'], color, emission=.4)
    for phase, points in (('SOLVER', row['result']['points']), ('PLANNER', row['plan']['reference'])):
        if not points: continue
        target = collection(f'{identifier} - {row["mode"]} - {phase}')
        obj = render._curve(target.name, points, center, identity, 0., max(.001, radius), material)
        move_to(obj, target); obj['termination'] = row['result']['termination']
        target.hide_viewport = target.hide_render = row['mode'] != 'INTEGRATED' or phase != 'SOLVER'


def set_inspection_view(points):
    from mathutils import Vector, Matrix
    values = np.asarray(points); center = values.mean(axis=0)
    _u, _s, axes = np.linalg.svd(values-center, full_matrices=False)
    if np.linalg.det(axes) < 0: axes[-1] *= -1
    rotation = Matrix(axes.T).to_quaternion(); size = max(np.ptp(values, axis=0))
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'VIEW_3D': continue
            space = area.spaces.active; space.shading.type = 'SOLID'; space.shading.color_type = 'MATERIAL'
            space.overlay.show_extras = False; space.region_3d.view_perspective = 'ORTHO'
            space.region_3d.view_rotation = rotation; space.region_3d.view_location = Vector(center)
            space.region_3d.view_distance = size*2


def main():
    options = arguments(); data = json.loads(Path(options.input).read_text(encoding='utf-8'))
    output = Path(options.output).resolve(); output.mkdir(parents=True, exist_ok=True); request = request_for(data)
    for seed in (False, True):
        for view in ('plane', 'depth'):
            name = f'{options.fiber}_{"seed" if seed else "recovery"}_{view}.png'
            camera_view(comparison(data, seed), request, output/name, view)
    inspection(data, options.fiber, output/f'{options.fiber}_inspection.blend')


if __name__ == '__main__': main()
