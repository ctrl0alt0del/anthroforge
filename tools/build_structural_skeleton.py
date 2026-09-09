"""Build a native, self-contained static skeleton from a reviewed fixture recipe.

Usage: blender --factory-startup -b -P tools/build_structural_skeleton.py -- study_dir
This is an authoring tool, not a runtime anatomical solver or a mesh lab replacement.
"""
import json
import math
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import anthroforge
from anthroforge.core.scp_runtime.object_roles import create_scp, set_scp_transform_object, set_scp_geometry_object
from anthroforge.core.scp_runtime.bound_objects import ensure_bound_object, sync_scp_roles
from anthroforge.app.use_cases.shortcuts import _append_shortcut
from anthroforge.core.scp_runtime.common import set_prop_raw
from anthroforge.core.scp_runtime.prop_update_guard import suppress_scp_prop_updates
from anthroforge.core.scp_runtime.attachment_runtime import capture_attachment_from_link as capture_attachment
from anthroforge.core.scp_runtime.runtime_state import attach_initialized
from anthroforge.core.utils import create_af_root

OUT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
RECIPE = json.loads((OUT / 'recipe.json').read_text())
DATA = np.load(OUT / 'structural_source.npz')
POINTS, TRIANGLES = DATA['points'], DATA['triangles']
OBJECTS, SCPS, CONTROLS, FIELDS = {}, {}, {}, {}
LONG = ('Femur.', 'Humerus.', 'Tibia.', 'Fibula.', 'Radius.', 'Ulna.', 'Clavicle.')


def collection(name):
    value = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(value)
    return value


def object_new(name, data, host):
    obj = bpy.data.objects.new(name, data)
    host.objects.link(obj)
    return obj


def prop(obj, name, value=1.0, minimum=0.85, maximum=1.15, description=''):
    obj[name] = value
    obj.id_properties_ui(name).update(min=minimum, max=maximum, soft_min=minimum, soft_max=maximum, description=description)


def driver(target, path, index, expression, variables):
    curve = target.driver_add(path, index)
    curve.driver.type = 'SCRIPTED'
    for name, obj, key in variables:
        var = curve.driver.variables.new()
        var.name, var.type = name, 'SINGLE_PROP'
        var.targets[0].id = obj
        var.targets[0].data_path = '["' + key + '"]'
    curve.driver.expression = expression


def mesh_object(name, vertices, faces, host):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    data.update()
    return object_new(name, data, host)


def bone_frame(points):
    mean = points.mean(0)
    _, axes = np.linalg.eigh(np.cov(points.T))
    z = axes[:, -1]
    z *= 1 if z[2] >= 0 else -1
    x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.8 else np.array([0.0, 1, 0])
    x = x - z * np.dot(z, x)
    x /= np.linalg.norm(x)
    basis = np.column_stack((x, np.cross(z, x), z))
    local = (points - mean) @ basis
    origin = mean + basis[:, 2] * local[:, 2].min()
    return origin, basis, (points - origin) @ basis


def frame_matrix(origin, basis):
    matrix = Matrix(np.column_stack((basis, origin)).tolist()).to_4x4()
    matrix[3] = (0, 0, 0, 1)
    return matrix


def faces_for(indices):
    inverse = np.full(len(POINTS), -1, dtype=int)
    inverse[indices] = np.arange(len(indices))
    faces = inverse[TRIANGLES]
    return faces[np.all(faces >= 0, axis=1)].tolist()


def create_bone(row):
    name, indices = row['name'], np.array(row['indices'])
    origin, basis, local = bone_frame(POINTS[indices])
    ctrl = object_new('CONTROL ' + name, None, HANDLES)
    ctrl.matrix_world = frame_matrix(origin, basis)
    ctrl.empty_display_type, ctrl.empty_display_size = 'PLAIN_AXES', 0.018
    obj = mesh_object(name, local.tolist(), faces_for(indices), BONES)
    obj.parent = ctrl
    obj.data.materials.append(MATERIALS[row['tissue']])
    for face in obj.data.polygons:
        face.use_smooth = True
    obj['anatomical_scope'], obj['source_components'] = name, row['components']
    obj['construction'] = 'Source-derived low-resolution bone cage; native deformation fields'
    OBJECTS[name], CONTROLS[name] = obj, ctrl
    register_bone(name, obj, ctrl, row)


def register_bone(name, obj, ctrl, row):
    scp = create_scp(ROOT, name)
    set_scp_transform_object(ROOT, scp, ctrl)
    set_scp_geometry_object(ROOT, scp, obj)
    set_prop_raw(scp, 'name', name)
    obj['af_structural_region'] = row['region']
    ctrl['anatomical_scope'] = name
    SCPS[name] = str(scp.id)
    if name.startswith(LONG):
        long_controls(name, row)


def lattice(name, matrix, dims, counts=(2, 2, 5)):
    data = bpy.data.lattices.new(name)
    data.points_u, data.points_v, data.points_w = counts
    data.interpolation_type_u = data.interpolation_type_v = data.interpolation_type_w = 'KEY_LINEAR'
    obj = object_new(name, data, PRIVATE)
    scale = [dims[i] / (counts[i] - 1) for i in range(3)]
    obj.matrix_world = matrix @ Matrix.Diagonal((*scale, 1))
    bpy.context.view_layer.update()
    obj.hide_render = True
    obj.display_type = 'WIRE'
    return obj


def modifier(obj, target, name, kind='LATTICE'):
    mod = obj.modifiers.new(name, kind)
    mod.object = target
    return mod


def local_lattice(name):
    obj, ctrl = OBJECTS[name], CONTROLS[name]
    points = np.array([v.co for v in obj.data.vertices])
    lo, hi = points.min(0), points.max(0)
    lat = lattice('PRIVATE cage ' + name, ctrl.matrix_world @ Matrix.Translation(Vector((lo + hi) / 2)), (hi - lo) * 1.02)
    world = lat.matrix_world.copy()
    lat.parent = ctrl
    lat.matrix_world = world
    return lat, points


def protected_group(obj, row):
    indices = np.array(row['indices'])
    points = POINTS[indices]
    weights = np.ones(len(points))
    contacts = [c for c in RECIPE['contacts'] if row['name'] in c['owners']]
    for contact in contacts:
        index = contact['source_vertices'][contact['owners'].index(row['name'])]
        distances = np.linalg.norm(points - POINTS[index], axis=1)
        radius = max(np.ptp(points, axis=0).max() * 0.13, 0.008)
        weights = np.minimum(weights, np.clip((distances - radius) / radius, 0, 1))
    group = obj.vertex_groups.new(name='Shape interior - joint interfaces protected')
    for i, weight in enumerate(weights):
        group.add([i], float(weight), 'REPLACE')
    return group.name


def long_controls(name, row):
    ctrl, obj = CONTROLS[name], OBJECTS[name]
    prop(ctrl, 'Shaft breadth', description='Local shape edit; contact neighborhoods protected')
    prop(ctrl, 'Shaft depth', description='Local shape edit; contact neighborhoods protected')
    prop(ctrl, 'Shaft bow m', 0.0, -0.006, 0.006, 'Curve-driven bow; joint interface vertices protected')
    lat, points = local_lattice(name)
    for point in lat.data.points:
        driver(point, 'co_deform', 0, f'{point.co_deform.x}*w', [('w', ctrl, 'Shaft breadth')])
        driver(point, 'co_deform', 1, f'{point.co_deform.y}*d', [('d', ctrl, 'Shaft depth')])
    mask = protected_group(obj, row)
    modifier(obj, lat, '01 Local shaft proportions').vertex_group = mask
    guide = local_curve(name, float(points[:, 2].max()))
    mod = modifier(obj, guide, '02 Shaft curvature', 'CURVE')
    mod.deform_axis, mod.vertex_group = 'POS_X', mask
    bind_private(name, [lat, guide])


def local_curve(name, length):
    ctrl = CONTROLS[name]
    data = bpy.data.curves.new('PRIVATE guide ' + name, 'CURVE')
    data.dimensions, data.resolution_u = '3D', 16
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(2)
    for i, point in enumerate(spline.bezier_points):
        point.co = (length * i / 2, 0, 0)
        point.handle_left_type = point.handle_right_type = 'AUTO'
    guide = object_new(data.name, data, PRIVATE)
    guide.parent = ctrl
    guide.rotation_euler.y = -math.pi / 2
    hook_middle(name, guide, length)
    return guide


def hook_middle(name, guide, length):
    ctrl = CONTROLS[name]
    hook = object_new('PRIVATE bow hook ' + name, None, PRIVATE)
    hook.parent = ctrl
    hook.location.z = length / 2
    hook.empty_display_size = 0.008
    mod = guide.modifiers.new('Object Mode bow control', 'HOOK')
    mod.object, mod.strength = hook, 1.0
    mod.vertex_indices_set([3, 4, 5])
    mod.matrix_inverse = Matrix.Translation((0, 0, -length / 2)) @ guide.matrix_basis
    driver(hook, 'location', 0, 'b', [('b', ctrl, 'Shaft bow m')])
    bind_private(name, [hook])


def bind_private(name, objects):
    for obj in objects:
        ensure_bound_object(ROOT, scp_named(name), obj)
    sync_scp_roles(ROOT, scp_named(name))


def scp_named(name):
    return next(scp for scp in ROOT.af_scp_system.scps if scp.id == SCPS[name])


def body_parameters():
    for key in ['Shin length', 'Thigh length', 'Lumbar height', 'Thorax height', 'Neck height', 'Head height', 'Pelvis breadth', 'Thorax breadth', 'Thorax depth', 'Head breadth', 'Head depth']:
        prop(ROOT, key, minimum=0.9, maximum=1.1, description='Shared continuous skeletal proportion field; relative to source')
    prop(ROOT, 'Overall stature', minimum=0.8, maximum=1.2, description='Uniform scale relative to the assumed 1.75 m baseline')
    for s in ['L', 'R']:
        for key in ['Upper arm length', 'Forearm length', 'Hand length']:
            prop(ROOT, key + '.' + s, minimum=0.9, maximum=1.1, description='Shared field for the complete arm and hand chain')


def landmark_height(name):
    row = next(r for r in RECIPE['bones'] if r['name'] == name)
    return float(POINTS[row['indices'], 2].mean())


def vertical_expression(z):
    bounds = [0, landmark_height('Patella.L'), landmark_height('Os_coxae.L'), landmark_height('Vertebra.T12'), landmark_height('Vertebra.C7'), landmark_height('Vertebra.C1'), RECIPE['normalization']['height_m']]
    names = ['Shin length', 'Thigh length', 'Lumbar height', 'Thorax height', 'Neck height', 'Head height']
    variables = [(f'p{i}', ROOT, name) for i, name in enumerate(names)]
    terms = [f'{max(0, min(z - lo, hi - lo))}*(p{i}-1)' for i, (lo, hi) in enumerate(zip(bounds, bounds[1:]))]
    return f'{z}+' + '+'.join(terms), variables


def body_weight(z, center, radius):
    return max(0.0, 1.0 - abs(z - center) / radius)


def body_lattice():
    lo, hi = POINTS.min(0), POINTS.max(0)
    dims = hi - lo
    lat = lattice('PRIVATE shared stature and torso cage', Matrix.Translation(Vector((lo + hi) / 2)), dims, (2, 2, 33))
    for point in lat.data.points:
        world = lat.matrix_world @ point.co_deform
        expression, variables = vertical_expression(world.z)
        driver(point, 'co_deform', 2, f'(({expression})*s-{lat.location.z})/{lat.scale.z}', variables + [('s', ROOT, 'Overall stature')])
        body_cross_driver(point, lat, lat.scale, world, 0)
        body_cross_driver(point, lat, lat.scale, world, 1)
    FIELDS['BODY'] = lat
    for obj in OBJECTS.values():
        modifier(obj, lat, '04 Shared stature and torso proportions')


def body_cross_driver(point, lat, dims, world, axis):
    z = world.z
    torso = body_weight(z, landmark_height('Vertebra.T5'), 0.28)
    head = min(1, max(0, (z - landmark_height('Vertebra.C2')) / 0.065))
    pelvis = max(0, 1 - max(0, z - landmark_height('Os_coxae.L')) / 0.22)
    key = 'breadth' if axis == 0 else 'depth'
    variables = [('t', ROOT, 'Thorax ' + key), ('h', ROOT, 'Head ' + key), ('s', ROOT, 'Overall stature')]
    addition = f'+{pelvis}*(p-1)' if axis == 0 else ''
    variables += [('p', ROOT, 'Pelvis breadth')] if axis == 0 else []
    factor = f'(1+{torso}*(t-1)+{head}*(h-1){addition})'
    expression = f'({world[axis]}*{factor}*s-{lat.location[axis]})/{dims[axis]}'
    driver(point, 'co_deform', axis, expression, variables)


def contact_point(name):
    record = next(c for c in RECIPE['contacts'] if c['name'] == name)
    return POINTS[record['source_vertices']].mean(0)


def arm_lattice(s):
    shoulder, elbow, wrist = [contact_point(name + '.' + s) for name in ['Shoulder', 'Elbow', 'Wrist']]
    names = [r['name'] for r in RECIPE['bones'] if r['region'] == 'ARM.' + s]
    points = np.concatenate([POINTS[r['indices']] for r in RECIPE['bones'] if r['name'] in names])
    z = (wrist - shoulder) / np.linalg.norm(wrist - shoulder)
    x = np.cross([0, 1, 0], z)
    x /= np.linalg.norm(x)
    basis = np.column_stack((x, np.cross(z, x), z))
    local = (points - shoulder) @ basis
    lo, hi = local.min(0), local.max(0)
    lat = lattice('PRIVATE whole arm ' + s, frame_matrix(shoulder + basis @ ((lo + hi) / 2), basis), (hi - lo) * 1.05, (2, 2, 17))
    configure_arm_points(lat, s, shoulder, elbow, wrist, basis, hi)
    FIELDS['ARM.' + s] = lat
    for name in names:
        modifier(OBJECTS[name], lat, '03 Shared arm chain proportions')


def configure_arm_points(lat, s, shoulder, elbow, wrist, basis, hi):
    cuts = [0, float((elbow - shoulder) @ basis[:, 2]), float((wrist - shoulder) @ basis[:, 2]), float(hi[2])]
    names = ['Upper arm length', 'Forearm length', 'Hand length']
    inverse = lat.matrix_world.inverted().to_3x3()
    direction = inverse @ Vector(basis[:, 2])
    for point in lat.data.points:
        q = float((np.array(lat.matrix_world @ point.co_deform) - shoulder) @ basis[:, 2])
        terms = [f'{max(0, min(q - lo, high - lo))}*(p{i}-1)' for i, (lo, high) in enumerate(zip(cuts, cuts[1:]))]
        variables = [(f'p{i}', ROOT, name + '.' + s) for i, name in enumerate(names)]
        driver(point, 'co_deform', 2, f'{point.co_deform.z}+{direction.z}*(' + '+'.join(terms) + ')', variables)


def parent_name(name):
    if name.startswith('Vertebra.'):
        order = [f'Vertebra.{r}{i}' for r, n in [('L', 5), ('T', 12), ('C', 7)] for i in range(n, 0, -1)]
        index = order.index(name)
        return 'Sacrum' if index == 0 else order[index - 1]
    if name.startswith('Rib.'):
        return 'Vertebra.T' + str(int(name.split('.')[1]))
    if name.startswith('Disc.'):
        return 'Vertebra.' + name.split('.')[1].split('_')[0]
    return other_parent(name)


def other_parent(name):
    base, _, side = name.rpartition('.')
    mapping = {'Femur': 'Os_coxae', 'Tibia': 'Femur', 'Fibula': 'Tibia', 'Patella': 'Femur', 'Tarsals': 'Tibia', 'Humerus': 'Scapula', 'Ulna': 'Humerus', 'Radius': 'Humerus', 'Carpals': 'Radius'}
    if base in mapping:
        return mapping[base] + '.' + side
    if name.startswith(('Finger.', 'Foot_ray.')):
        return ('Carpals.' if name.startswith('Finger.') else 'Tarsals.') + side
    if name.startswith(('Os_coxae.', 'Scapula.', 'Clavicle.', 'Costal_cartilage.')):
        return {'Os_coxae': 'Sacrum', 'Scapula': 'Vertebra.T2', 'Clavicle': 'Sternum', 'Costal_cartilage': 'Sternum'}[name.split('.')[0]]
    return {'Cranium': 'Vertebra.C1', 'Mandible': 'Cranium', 'Hyoid': 'Vertebra.C3', 'Sternum': 'Vertebra.T4', 'HipCartilage': 'Sacrum'}.get(name, '')


def attach_bones():
    bpy.context.view_layer.update()
    for name in SCPS:
        scp = scp_named(name)
        parent = parent_name(name)
        if not parent:
            continue
        set_prop_raw(scp, 'parent_id', SCPS[parent])
        set_prop_raw(scp, 'attach_parent_anchor_mode', 'OBJECT_ORIGIN')
        set_prop_raw(scp, 'attach_child_anchor_mode', 'OBJECT_ORIGIN')
        ok = capture_attachment(scp, CONTROLS[name], OBJECTS[name], CONTROLS[parent], OBJECTS[parent])
        if not ok and not attach_initialized(scp):
            raise RuntimeError('Cannot capture hierarchy: ' + name)
        CONTROLS[name]['hierarchy_parent'] = parent
        CONTROLS[name]['hierarchy_note'] = 'Origin frame scaffold; shared fields handle proportion edits. Not a physical joint constraint.'


def markers():
    for contact in RECIPE['contacts']:
        for i, owner in enumerate(contact['owners']):
            point = POINTS[contact['source_vertices'][i]]
            marker = mesh_object('CONTACT ' + contact['name'] + (' parent' if i == 0 else ' child'), [point.tolist()], [], LANDMARKS)
            marker['contact_name'], marker['owner'], marker['anatomical_center'] = contact['name'], owner, False
            region = OBJECTS[owner]['af_structural_region']
            if region in FIELDS:
                modifier(marker, FIELDS[region], '03 Shared arm chain proportions')
            modifier(marker, FIELDS['BODY'], '04 Shared stature and torso proportions')
            marker.hide_render = True


def material_new(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def documentation():
    text = bpy.data.texts.new('START HERE - structural skeleton')
    text.write('Select AF_ROOT, Object Properties > Custom Properties for stature, regional lengths and breadths.\n')
    text.write('Select a long bone; its AnthroForge shortcuts expose shaft breadth, depth and bow in Object Mode. The same properties live on its CONTROL object.\n')
    text.write('Shared arm and body lattices move adjacent bones together. The original gaps remain represented.\n')
    text.write('Geometry: source-derived low-resolution cages. Separate vertebrae, ribs, pelvis halves, scapular processes and joint ends are retained.\n')
    text.write('Primitive replacement and anatomical joint-center fitting are not completed by this tool. Contact markers are derived vertex-pair proxies.\n')
    text.write('Native hierarchy supports rigid authoring transforms; it is not an IK or joint-limit solver. Proportion fields are defined in the saved reference pose.\n')
    text.write('Do not apply/remove modifiers or change topology after binding muscles without rebinding. Bone-region names do not specify muscle footprints.\n')
    text.write('Coordinate convention: +X anatomical left, +Y posterior, +Z superior. Baseline height 1.75 m is assumed.\n')
    text.write('Source and evidence: ' + str(OUT / 'recipe.json') + '\n')
    data = bpy.data.texts.new('Structural source and control manifest.json')
    data.write(json.dumps(RECIPE, indent=2))


def finish():
    documentation()
    ROOT['model_status'] = 'Structural working model - see START HERE text for scope and limitations'
    ROOT['source_sha256'] = RECIPE['source_sha256']
    ROOT['normalization_height_m'] = 1.75
    present_controls()
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    ROOT.select_set(True)
    bpy.context.view_layer.objects.active = ROOT
    configure_view()
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'structural_skeleton.blend'))


def present_controls():
    ROOT.empty_display_size = 0.06
    for obj in PRIVATE.objects:
        obj.hide_set(True)
    for obj in LANDMARKS.objects:
        obj.hide_set(True)
    for name, obj in CONTROLS.items():
        obj.hide_set(not name.startswith(LONG))


def configure_view():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_distance = 2.8
                area.spaces.active.region_3d.view_location = (0, 0, 0.88)
                area.spaces.active.region_3d.view_rotation = Vector((0, 1, 0)).to_track_quat('-Z', 'Y')
                area.spaces.active.shading.color_type = 'MATERIAL'
                area.spaces.active.clip_end = 100


def build():
    body_parameters()
    with suppress_scp_prop_updates():
        for row in RECIPE['bones']:
            create_bone(row)
        arm_lattice('L')
        arm_lattice('R')
        body_lattice()
        attach_bones()
    markers()
    shape_shortcuts()
    finish()
    print('STRUCTURAL_SKELETON_SAVED', len(SCPS), flush=True)


def shape_shortcuts():
    for name, ctrl in CONTROLS.items():
        if not name.startswith(LONG):
            continue
        scp = scp_named(name)
        bound = next(entry.id for entry in scp.bound_objects if entry.object_ref == ctrl)
        for key in ['Shaft breadth', 'Shaft depth', 'Shaft bow m']:
            path = f'af://scp_bound_rna/{scp.id}|{bound}/["{key}"]'
            _append_shortcut(ROOT.af_shortcut_system.shortcuts, key, path, ('SCP', scp.id))


if not bpy.app.background:
    raise RuntimeError('Run this authoring tool in a separate background Blender process.')
bpy.ops.wm.read_factory_settings(use_empty=True)
anthroforge.register()
ROOT = create_af_root(bpy.context.scene)
BONES, HANDLES, PRIVATE, LANDMARKS = [collection(n) for n in ['Skeleton - structural surfaces', 'Controls - bone shape', 'Private - curves lattices hooks', 'Evidence - contact proxies']]
MATERIALS = {'BONE': material_new('Bone - ivory', (0.79, 0.72, 0.58, 1)), 'CARTILAGE': material_new('Cartilage - blue', (0.22, 0.45, 0.49, 1))}
build()
