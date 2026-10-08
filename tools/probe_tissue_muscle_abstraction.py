"""Bounded design experiments; no production behavior or authoring records changed."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / 'tests/blender')]
import anthroforge
from _helpers import ensure_addon_registered, select_only
from test_muscle_vcp_workflows import _muscle_setup, _surface_obj
from core.visualization.fiber_surface_sync import find_fiber_surface_proxy
from core.visualization.soft_tissue_source import sample_entity_base
from core.visualization.muscle_numeric_runtime import _numeric_spec
from core.vcp.muscle_envelope_native import legacy, section
from core.vcp.muscle_section_profile import SectionProfileSpec
from core.vcp.soft_tissue_surface_inflation import SurfaceLayerProfile, inflate_surface_layer
from core.vcp.soft_tissue_surface_field import boundary_edges
from core.vcp.soft_tissue_static_envelope import StaticEnvelopeSettings, solve_static_envelope

OUT = ROOT / 'artifacts/tissue_muscle_abstraction/v1'


def points(obj):
    return np.array([tuple(obj.matrix_world @ v.co) for v in obj.data.vertices])


def shared_source():
    root, first, second = _muscle_setup()
    select_only(first); second.select_set(True)
    assert bpy.ops.af.add_muscle_vcp() == {'FINISHED'}
    muscle = root.af_vcp_system.muscles[0]
    surface = root.af_vcp_system.fiber_surfaces[0]
    source = find_fiber_surface_proxy(bpy.context.scene, root.name, surface.id)
    select_only(source)
    bpy.context.scene.af_new_soft_tissue_preset = 'CUSTOM'
    assert bpy.ops.af.add_soft_tissue_vcp() == {'FINISHED'}
    tissue = root.af_vcp_system.soft_tissues[0]
    sample = sample_entity_base(root, bpy.context.scene, tissue)
    base = points(_surface_obj(root, muscle, 'BASE'))
    report = shared_report(base, sample, source, muscle, tissue)
    return muscle, surface, report


def shared_report(base, sample, source, muscle, tissue):
    delta = lambda a, b: float(np.max(np.linalg.norm(a-b, axis=1)))
    return dict(count=len(base), muscle_sample_error=delta(base, np.array(sample.points)),
                source_sample_error=delta(points(source), np.array(sample.points)),
                same_source_id=muscle.fiber_surface_id == tissue.base_source_id,
                target_type=tissue.attachment_target_type)


def grid(warped):
    u, v = np.meshgrid(np.linspace(-1, 1, 25), np.linspace(-.5, .5, 13))
    z = .4*u*u + .3*u*v if warped else np.zeros_like(u)
    return np.stack((u, v, z), axis=-1)


def topology(g):
    m, n = g.shape[:2]
    return tuple((i*n+j, (i+1)*n+j, (i+1)*n+j+1, i*n+j+1)
                 for i in range(m-1) for j in range(n-1))


def normals(g, faces):
    mesh = bpy.data.meshes.new('Probe normal sampling')
    mesh.from_pydata(g.reshape(-1, 3).tolist(), [], faces); mesh.update()
    values = np.array([tuple(v.normal) for v in mesh.vertices])
    bpy.data.meshes.remove(mesh)
    return values


def native_shape(g, spec, mode):
    if mode == 'SECTION':
        return section(g, SectionProfileSpec(depths=(.1, .25, .25, .1), direction='SECTION'), 1)
    return legacy(g, replace(spec, inflation_mode=mode, inflation_max_value=.25,
                            control_world=(0., 0., 0.), inflation_direction_depth=.3))


def normal_projection(g, result, faces):
    base, front = g.reshape(-1, 3), result.reshape(-1, 3)
    direction = normals(g, faces)
    delta = front-base
    height = np.sum(delta*direction, axis=1)
    if np.sum(height) < 0: direction, height = -direction, -height
    amount = max(float(height.max()), 1.e-9)
    shell = inflate_surface_layer(base, direction, faces, boundary_edges((), faces),
                                  np.clip(height/amount, 0, 1), SurfaceLayerProfile(amount, 0, 1))
    error = np.linalg.norm(front-np.array(shell.vertices[:len(base)]), axis=1)
    return shell, dict(max_error=float(error.max()), rms_error=float(np.sqrt(np.mean(error**2))),
                       max_displacement=float(np.linalg.norm(delta, axis=1).max()))


def relax_native_front(g, result, shell):
    count = g.shape[0]*g.shape[1]
    vertices = tuple(map(tuple, result.reshape(-1, 3))) + tuple(map(tuple, g.reshape(-1, 3)))
    rim = {v for edge in boundary_edges((), topology(g)) for v in edge}
    settings = StaticEnvelopeSettings(iterations=110, gravity=(0., -1., 0.))
    solved = solve_static_envelope(vertices, shell.faces, tuple(rim | set(range(count, 2*count))), count, settings)
    return solved, vertices


def mesh_view(name, vertices, faces, offset, color):
    mesh = bpy.data.meshes.new(name); mesh.from_pydata(vertices, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh); bpy.context.scene.collection.objects.link(obj)
    obj.location, obj.color = offset, color
    return obj


def run_cases(spec):
    reports = {}
    for warped in (False, True):
        g = grid(warped); faces = topology(g)
        for index, mode in enumerate(('DISTRIBUTED', 'CTRL_POINT', 'SECTION')):
            result = native_shape(g, spec, mode)
            shell, report = normal_projection(g, result, faces)
            reports[f'{"curved" if warped else "flat"}_{mode}'] = report
            if warped:
                mesh_view(mode, result.reshape(-1, 3).tolist(), faces, (index*2.7, 0, 0), (.7, .23, .17, 1))
                mesh_view(mode+' normal projection', shell.vertices, shell.faces, (index*2.7, 1.6, 0), (.15, .5, .7, 1))
    solved, rest = relax_native_front(g, result, shell)
    mesh_view('Section plus native relaxation', solved.vertices, shell.faces, (5.4, 3.2, 0), (.6, .4, .12, 1))
    reports['section_then_relaxation'] = solved.report
    return reports


def render():
    scene = bpy.context.scene
    camera = bpy.data.objects.new('Probe camera', bpy.data.cameras.new('Probe camera'))
    scene.collection.objects.link(camera); scene.camera = camera
    center = Vector((2.7, 1.3, 0)); camera.location = center + Vector((0, -7, -10))
    camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type, camera.data.ortho_scale = 'ORTHO', 9
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.color_type = 'OBJECT'
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1200, 800, 100
    scene.render.filepath = str(OUT / 'comparison.png')
    bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    ensure_addon_registered(); OUT.mkdir(parents=True, exist_ok=True)
    muscle, surface, shared = shared_source()
    spec = _numeric_spec(muscle, surface, 25, False, False)
    for obj in tuple(bpy.data.objects): bpy.data.objects.remove(obj, do_unlink=True)
    reports = dict(shared_source=shared, experiments=run_cases(spec))
    (OUT / 'results.json').write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports, indent=2)); render()
