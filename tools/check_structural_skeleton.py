"""Native behavioral checks and calibrated views for the structural skeleton study."""
import json
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.core.shortcuts import resolve_shortcut

OUT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
RECIPE = json.loads((OUT / 'recipe.json').read_text())
DATA = np.load(OUT / 'structural_source.npz')
POINTS = DATA['points']


def refresh():
    ROOT.update_tag()
    for obj in CONTROLS:
        obj.update_tag()
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()


def mesh_points(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    points = np.array([evaluated.matrix_world @ v.co for v in mesh.vertices])
    evaluated.to_mesh_clear()
    return points


def snapshot():
    return {r['name']: mesh_points(bpy.data.objects[r['name']]) for r in RECIPE['bones']}


def errors(a, b):
    return {name: float(np.linalg.norm(a[name] - b[name], axis=1).max()) for name in a}


def contacts(snapshot):
    result = {}
    lookup = {r['name']: {v: i for i, v in enumerate(r['indices'])} for r in RECIPE['bones']}
    for contact in RECIPE['contacts']:
        a, b = contact['owners']
        i, j = contact['source_vertices']
        pair = [snapshot[a][lookup[a][i]], snapshot[b][lookup[b][j]]]
        result[contact['name']] = float(np.linalg.norm(pair[0] - pair[1]))
    return result


def controls():
    return [(o, k, float(o[k])) for o in [ROOT] + CONTROLS for k in o.keys() if k[0].isupper() and o.id_properties_ui(k).as_dict().get('min') is not None and isinstance(o[k], float)]


def reset(parameters):
    for obj, key, value in parameters:
        obj[key] = value
    refresh()


def field_min_determinant():
    values = []
    for obj in bpy.data.objects:
        if obj.type != 'LATTICE':
            continue
        data = obj.data
        points = np.array([p.co_deform for p in data.points]).reshape(data.points_w, data.points_v, data.points_u, 3)
        for k in range(data.points_w - 1):
            a = points[k, 0, 1] - points[k, 0, 0]
            b = points[k, 1, 0] - points[k, 0, 0]
            c = points[k + 1, 0, 0] - points[k, 0, 0]
            values.append(float(np.linalg.det(np.column_stack((a, b, c)))))
    return min(values)


def trial(label, baseline, base_contacts):
    refresh()
    state = snapshot()
    gap = contacts(state)
    drift = errors(state, baseline)
    return dict(label=label, finite=all(np.isfinite(p).all() for p in state.values()), max_displacement_m=max(drift.values()), moved_bones=sum(v > 1e-6 for v in drift.values()), max_contact_gap_change_m=max(abs(gap[n] - base_contacts[n]) for n in gap), minimum_cage_cell_determinant=field_min_determinant())


def individual_trials(parameters, baseline, base_contacts):
    results = []
    for obj, key, value in parameters:
        bounds = obj.id_properties_ui(key).as_dict()
        for extreme in ['min', 'max']:
            obj[key] = bounds[extreme]
            results.append(trial(obj.name + ' / ' + key + ' / ' + extreme, baseline, base_contacts))
            obj[key] = value
    reset(parameters)
    return results


def combined_trials(parameters, baseline, base_contacts):
    results = []
    for extreme in ['min', 'max']:
        for obj, key, _ in parameters:
            obj[key] = obj.id_properties_ui(key).as_dict()[extreme]
        results.append(trial('combined_' + extreme, baseline, base_contacts))
        render('structural_' + extreme, (0, -1, 0))
    reset(parameters)
    return results


def render(name, direction):
    camera = bpy.data.objects.get('Study camera')
    if camera is None:
        camera = bpy.data.objects.new('Study camera', bpy.data.cameras.new('Study camera'))
        bpy.context.scene.collection.objects.link(camera)
    center, scale = framing()
    camera.location = center + Vector(direction).normalized() * 5
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type, camera.data.ortho_scale = 'ORTHO', scale
    bpy.context.scene.camera = camera
    bpy.context.scene.render.filepath = str(OUT / (name + '.png'))
    bpy.ops.render.render(write_still=True)


def framing():
    points = np.concatenate(list(snapshot().values()))
    lo, hi = points.min(0), points.max(0)
    scale = max(hi[2] - lo[2], (hi[0] - lo[0]) * 1350 / 1100) * 1.14
    return Vector((lo + hi) / 2), float(scale)


def render_setup():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = 1100, 1350
    scene.render.resolution_percentage = 100
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_cavity = True
    scene.display.shading.show_shadows = True
    scene.display.shading.background_type = 'WORLD'
    scene.world = bpy.data.worlds.new('Study world') if scene.world is None else scene.world
    scene.world.color = (0.055, 0.065, 0.085)


def validation():
    refresh()
    baseline = snapshot()
    source = {r['name']: POINTS[r['indices']] for r in RECIPE['bones']}
    result = dict(bones=len(baseline), source_errors_m=errors(baseline, source), source_contact_gaps_m=contacts(source))
    parameters, base_contacts = controls(), contacts(baseline)
    result['parameter_count'] = len(parameters)
    result['trials'] = individual_trials(parameters, baseline, base_contacts)
    result['trials'] += combined_trials(parameters, baseline, base_contacts)
    result['reset_errors_m'] = errors(snapshot(), baseline)
    result['failed_driver_count'] = failed_drivers()
    result['shortcut_errors'] = [s.name for s in ROOT.af_shortcut_system.shortcuts if resolve_shortcut(ROOT, bpy.context, s.data_path).error]
    result['order_error_m'] = order_check(parameters)
    save_result(result, baseline)


def save_result(result, baseline):
    (OUT / 'validation.json').write_text(json.dumps(result, indent=2))
    np.savez_compressed(OUT / 'saved_baseline.npz', **baseline)
    acceptance(result)
    print('VALIDATED', json.dumps({k: v for k, v in result.items() if k in ['bones', 'parameter_count', 'failed_driver_count']}), flush=True)


def order_check(parameters):
    for obj, key, _ in parameters:
        obj[key] = obj.id_properties_ui(key).as_dict()['max']
    refresh()
    forward = snapshot()
    reset(parameters)
    for obj, key, _ in reversed(parameters):
        obj[key] = obj.id_properties_ui(key).as_dict()['max']
    refresh()
    error = max(errors(snapshot(), forward).values())
    reset(parameters)
    return error


def acceptance(result):
    assigned = [i for row in RECIPE['bones'] for i in row['indices']]
    assert len(assigned) == len(set(assigned)) == len(POINTS), 'Source scope has omissions or duplicate ownership'
    assert max(result['source_errors_m'].values()) < 2e-6, 'Default construction changed source anatomy'
    assert max(result['reset_errors_m'].values()) < 2e-6, 'Edits are not reversible'
    assert result['order_error_m'] < 2e-6, 'Edit order affects geometry'
    assert result['failed_driver_count'] == 0, 'Invalid native drivers'
    assert not result['shortcut_errors'], 'Unresolved addon shortcuts'
    assert all(t['finite'] and t['moved_bones'] > 0 for t in result['trials']), 'Inactive or invalid control'
    assert all(t['minimum_cage_cell_determinant'] > 0 for t in result['trials']), 'Inverted sampled cage cell'
    assert max(t['max_contact_gap_change_m'] for t in result['trials']) < 0.005, 'Contact change exceeds study bound'


def failed_drivers():
    data = list(bpy.data.objects) + list(bpy.data.lattices) + list(bpy.data.curves)
    return sum(not c.driver.is_valid for obj in data if obj.animation_data for c in obj.animation_data.drivers)


def main():
    render_setup()
    validation()
    render('structural_front', (0, -1, 0))
    render('structural_oblique', (1, -2, 0.2))
    render('structural_back', (0, 1, 0))
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'structural_skeleton.blend'))


if not hasattr(bpy.types.Object, 'af_scp_system'):
    anthroforge.register()
ROOT = bpy.data.objects['AF_ROOT']
CONTROLS = [o for o in bpy.data.objects if o.name.startswith('CONTROL ')]
if __name__ == '__main__':
    main()
