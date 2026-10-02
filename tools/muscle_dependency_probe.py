"""AF-14 production-copy timing probe, adapted from the September muscle edit probe."""
import argparse
import cProfile
import hashlib
import json
import os
import platform
import pstats
import sys
import time
import traceback
from pathlib import Path
import bpy
import numpy as np

STATE = {}
COUNTERS = {}


def args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True)
    parser.add_argument('--checkout', required=True)
    parser.add_argument('--save-blend', default='')
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', default='inventory')
    parser.add_argument('--muscle', default='')
    parser.add_argument('--repeats', type=int, default=6)
    parser.add_argument('--property', default='')
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save():
    result = STATE['result']
    result['source_unchanged'] = result['source_sha256'] == digest(STATE['args'].file)
    Path(STATE['args'].output).write_text(json.dumps(result, indent=2, default=_json_default), encoding='utf-8')


def _json_default(value):
    return value.to_list() if hasattr(value, "to_list") else str(value)


def root():
    from anthroforge.core.utils import get_af_root
    return get_af_root(bpy.context.scene)


def proxy(muscle, kind='INFL'):
    return next((o for o in bpy.context.scene.objects if o.get('af_muscle_proxy')
                 and o.get('af_muscle_id') == muscle.id
                 and o.get('af_muscle_surface') == kind), None)


def inventory():
    vcp = root().af_vcp_system
    return dict(objects=len(bpy.context.scene.objects), fibers=len(vcp.fibers),
                surfaces=len(vcp.fiber_surfaces), muscles=[muscle_row(m) for m in vcp.muscles])


def muscle_row(muscle):
    objects = [o for o in bpy.context.scene.objects if o.get('af_muscle_id') == muscle.id]
    return dict(id=muscle.id, name=muscle.name, source=muscle.surface_source_mode,
                mode=muscle.inflation_mode, material=bool(muscle.get('af_authoring_material')),
                amount=muscle.inflation_max_value, radius=muscle.inflation_falloff_radius,
                objects=[object_row(o) for o in objects])


def object_row(obj):
    return dict(name=obj.name, type=obj.type, tags=dict(obj.items()),
                vertices=len(obj.data.vertices) if obj.type == 'MESH' else 0,
                modifiers=[(m.name, m.type) for m in obj.modifiers])


def metadata():
    return dict(source=STATE['args'].file, source_sha256=digest(STATE['args'].file),
                blender=bpy.app.version_string, blender_hash=bpy.app.build_hash.decode(),
                background=bpy.app.background, platform=platform.platform(), python=sys.version, checkout=STATE['args'].checkout,
                environment={k:v for k,v in os.environ.items() if k.startswith(('AF_', 'OMP_'))},
                events=[], inventory=inventory(), source_identity=source_identity())


def source_identity():
    import subprocess
    folder = Path(STATE['args'].checkout)
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=folder, text=True).splitlines()
    rows = {name: digest(folder / name) for name in paths if (folder / name).is_file()}
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    Path(STATE['args'].output + '.sources.json').write_text(json.dumps(rows, indent=2), encoding='utf8')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=folder, text=True).strip()
    return dict(head=head, fingerprint=fingerprint, path=str(folder), manifest=STATE['args'].output + '.sources.json')


def wrap(owner, name, label):
    original = getattr(owner, name)
    def measured(*values, **options):
        started = time.perf_counter()
        try: return original(*values, **options)
        finally:
            row = COUNTERS.setdefault(label, [0, 0.0])
            row[0] += 1
            row[1] += (time.perf_counter() - started) * 1000
    setattr(owner, name, measured)


def instrumentation():
    from anthroforge.core.visualization import muscle_sync as ms, muscle_numeric_runtime as nr
    from anthroforge.core.deps import runtime_trace as rt
    for name in ('capture_muscle_work', 'execute_muscle_work', 'publish_muscle_work'):
        wrap(ms, name, name)
    for name in ('_update_mesh', '_process_ctrl_point_update', '_sync_control'):
        owner = nr if name == '_sync_control' else ms.MuscleSceneSync
        wrap(owner, name, name)
    rt.set_request_telemetry(True)
    detail_instrumentation()
    if STATE['args'].mode in {'detail', 'profile'}: codec_instrumentation()


def detail_instrumentation():
    from anthroforge.core.deps import runtime_context_build as cb
    from anthroforge.core.visualization import fiber_sync_runtime as fr
    from anthroforge.core.scp_runtime import surface as sf
    for owner,names in ((cb, ('_graph_stamp', '_graph_data')),
                        (fr, ('_depsgraph_changed_fibers',)),
                        (sf, ('surface_bvh_local', '_build_surface_uncached', '_surface_route_graph'))):
        for name in names: wrap(owner, name, name)
    control_trace()
    bpy.app.handlers.depsgraph_update_post.append(update_inventory)


def update_inventory(scene, depsgraph):
    updates = tuple(depsgraph.updates)
    STATE.setdefault('update_inventory', []).append(dict(count=len(updates),
        geometry=sum(bool(u.is_updated_geometry) for u in updates),
        transform=sum(bool(u.is_updated_transform) for u in updates)))


def control_trace():
    from anthroforge.core.visualization.muscle_sync import MuscleSceneSync
    from anthroforge.core.vcp.runtime_state import muscle_inflation_ctrl_world
    original = MuscleSceneSync._process_ctrl_point_update
    def measured(sync, owner, collection, obj, changed):
        muscle = sync._find_muscle(owner, obj.get('af_muscle_id'))
        row = dict(incoming=tuple(obj.location), stored=muscle_inflation_ctrl_world(muscle))
        STATE.setdefault('control_trace', []).append(row)
        result = original(sync, owner, collection, obj, changed)
        row.update(result=result, snapped=tuple(obj.location), final=muscle_inflation_ctrl_world(muscle))
        return result
    MuscleSceneSync._process_ctrl_point_update = measured


def select(muscle):
    from anthroforge.core.visualization.muscle_sync import register_muscle_sync
    vcp = root().af_vcp_system
    vcp.active_vcp_type, vcp.active_vcp_id = 'MUSCLE', muscle.id
    for obj in bpy.context.selected_objects: obj.select_set(False)
    targets = [o for o in bpy.context.scene.objects if o.get('af_muscle_proxy') and o.get('af_muscle_id') == muscle.id]
    if targets:
        targets[-1].select_set(True)
        bpy.context.view_layer.objects.active = targets[-1]
    register_muscle_sync().sync_root_to_scene(root(), bpy.context.scene, {muscle.id})
    bpy.context.view_layer.update()


def geometry():
    result = {}
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or not obj.get('af_muscle_proxy'): continue
        coordinates = np.empty(len(obj.data.vertices)*3, dtype=np.float32)
        obj.data.vertices.foreach_get('co', coordinates)
        result[obj.name] = dict(hash=hashlib.sha256(coordinates.tobytes()).hexdigest(),
            vertices=len(obj.data.vertices), finite=bool(np.isfinite(coordinates).all()),
            state=obj.get('af_muscle_output_state', ''), backend=obj.get('af_muscle_numeric_backend', ''))
    return result


def plans(muscle):
    count = STATE['args'].repeats
    names = ('inflation_max_value', 'inflation_falloff_radius', 'inflation_direction_depth',
             'inflation_boundary_strength', 'inflation_length_taper_band')
    if muscle.inflation_mode == 'CTRL_POINT': names += ('control_move',)
    if STATE['args'].property: names = tuple(STATE['args'].property.split(','))
    base = {name:float(getattr(muscle,name,0)) for name in names if name != "section_depths"}
    return [(name, i, base.get(name, 0)) for name in names for i in range(count)]


def apply_event(muscle, name, index, baseline):
    if name == 'section_depths':
        muscle.section_depths = tuple(v*(1.1 if index % 2 == 0 else 1/1.1) for v in muscle.section_depths)
        return tuple(muscle.section_depths)
    if name == 'recompute': return recompute(muscle)
    if name == 'inflation_burst': return burst(muscle)
    if name == 'control_operator': return operator_move(muscle, index)
    if name != 'control_move':
        value = baseline if index % 2 else changed_value(muscle, name, baseline)
        setattr(muscle, name, value)
        return value
    ctrl = next(o for o in bpy.context.scene.objects if o.get('af_muscle_inflation_ctrl') and o.get('af_muscle_id') == muscle.id)
    ctrl.location.x += .002 if index % 2 == 0 else -.002
    return tuple(ctrl.location)


def changed_value(muscle, name, baseline):
    prop = muscle.bl_rna.properties[name]
    delta = max(abs(baseline)*.1, .001)
    return baseline+delta if baseline+delta <= prop.hard_max else max(prop.hard_min,baseline-delta)


def burst(muscle):
    value = float(muscle.inflation_max_value)
    for index in range(20):
        muscle.inflation_max_value = value * (1 + .01 * (index % 10 + 1))
    return float(muscle.inflation_max_value)


def operator_move(muscle, index):
    ctrl = next(o for o in bpy.context.scene.objects if o.get('af_muscle_inflation_ctrl') and o.get('af_muscle_id') == muscle.id)
    for obj in bpy.context.selected_objects: obj.select_set(False)
    ctrl.select_set(True); bpy.context.view_layer.objects.active = ctrl
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.transform.translate(value=(.002 if index % 2 == 0 else -.002,0,0))
    return tuple(ctrl.location)


def measured_event(plan):
    from anthroforge.core.deps.runtime_trace import clear_request_telemetry
    name,index,baseline = plan
    clear_request_telemetry(); COUNTERS.clear()
    STATE['control_trace'] = []
    STATE['update_inventory'] = []
    before = geometry(); started = time.perf_counter()
    value = apply_event(STATE['muscle'], name, index, baseline)
    callback = time.perf_counter()
    bpy.context.view_layer.update()
    finished = time.perf_counter()
    for area in bpy.context.screen.areas: area.tag_redraw()
    return dict(property=name, index=index, value=value, callback_ms=(callback-started)*1000,
                callback_depsgraph_ms=(finished-started)*1000, started=started, before=before)


def complete_event(event):
    from anthroforge.core.deps.runtime_trace import request_telemetry
    after = geometry(); before = event.pop('before')
    event['observed_settled_ms'] = (time.perf_counter()-event.pop('started'))*1000
    event['changed_meshes'] = [key for key in after if after[key] != before.get(key)]
    event['geometry'] = after; event['telemetry'] = request_telemetry(clear=True)
    event['instrumentation'] = dict(COUNTERS)
    event['control_trace'] = list(STATE.get('control_trace', ()))
    event['depsgraph_updates'] = list(STATE.get('update_inventory', ()))
    STATE['result']['events'].append(event)
    print('MUSCLE_EDIT', event['property'], round(event['callback_depsgraph_ms'],2), flush=True)
    save()


def draw_timestamp():
    event = STATE.get('pending')
    if event and 'first_draw_ms' not in event:
        event['first_draw_ms'] = (time.perf_counter()-event['started'])*1000


def tick():
    try: return advance()
    except Exception:
        STATE['result']['error'] = traceback.format_exc(); save()
        print(STATE['result']['error'], flush=True)
        bpy.ops.wm.quit_blender()


def advance():
    if STATE.get('pending'):
        complete_event(STATE.pop('pending'))
    if not STATE['plans']:
        save_blend(); save(); bpy.ops.wm.quit_blender(); return None
    STATE['pending'] = measured_event(STATE['plans'].pop(0))
    return .3


def prepare():
    muscle = next(m for m in root().af_vcp_system.muscles if m.name == STATE['args'].muscle or m.id == STATE['args'].muscle)
    STATE['muscle'] = muscle
    started = time.perf_counter(); select(muscle)
    STATE['result']['selection_setup_ms'] = (time.perf_counter()-started)*1000
    if STATE['args'].mode != 'plain': instrumentation()
    return start_measurements(muscle)


def start_measurements(muscle):
    STATE['plans'] = plans(muscle)
    if STATE['args'].mode == 'visual': return visuals()
    if STATE['args'].mode == 'profile': return profile_run()
    bpy.types.SpaceView3D.draw_handler_add(draw_timestamp, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.timers.register(tick, first_interval=1)


def viewport_snapshot(filename):
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    scene = bpy.context.scene; scene.render.resolution_x = 1000; scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100; scene.render.filepath = filename
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.render.opengl(write_still=True, view_context=True)


def visuals():
    muscle = STATE['muscle']; target = proxy(muscle)
    for obj in bpy.context.selected_objects: obj.select_set(False)
    target.select_set(True); bpy.context.view_layer.objects.active = target
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    clean_visual(area, target)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    frame_visual(area, region)
    folder = Path(STATE['args'].output).parent
    viewport_snapshot(str(folder / 'pectoralis_before.png'))
    muscle.inflation_max_value *= 1.5; bpy.context.view_layer.update()
    viewport_snapshot(str(folder / 'pectoralis_inflation_plus50.png'))
    save(); bpy.ops.wm.quit_blender()


def clean_visual(area, target):
    area.spaces.active.shading.show_xray = False
    area.spaces.active.overlay.show_overlays = False
    for obj in bpy.context.scene.objects:
        hide = obj.get('af_muscle_proxy') or obj.get('af_fiber_surface_proxy') or obj.get('af_fiber_proxy')
        if hide and obj != target: obj.hide_set(True)


def frame_visual(area, region):
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_axis(type='FRONT')
        bpy.ops.view3d.view_selected()


def profile_run():
    profiler = cProfile.Profile(); profiler.enable()
    event = measured_event(STATE['plans'][0]); complete_event(event)
    profiler.disable(); profiler.dump_stats(STATE['args'].output + '.pstats')
    stats = pstats.Stats(profiler)
    rows = [dict(file=k[0], line=k[1], function=k[2], calls=v[1], self_ms=v[2]*1000, cumulative_ms=v[3]*1000) for k,v in stats.stats.items()]
    STATE['result']['profile'] = sorted(rows, key=lambda x:-x['cumulative_ms'])[:100]
    save(); bpy.ops.wm.quit_blender()


def main():
    STATE['args'] = args()
    anthroforge = load_checkout()
    if not hasattr(bpy.types.Object, 'af_scp_system'): anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=STATE['args'].file)
    STATE['result'] = metadata(); save()
    if STATE['args'].mode == 'inventory': bpy.ops.wm.quit_blender(); return
    if bpy.app.background: prepare()
    else: bpy.app.timers.register(prepare, first_interval=3)


def load_checkout():
    import importlib.util
    folder = Path(STATE['args'].checkout)
    spec = importlib.util.spec_from_file_location('anthroforge', folder / '__init__.py', submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec); sys.modules['anthroforge'] = module
    spec.loader.exec_module(module)
    return module


def codec_instrumentation():
    from anthroforge.core.vcp import fiber_node_attachment_codec as codec
    for name in ('decode_node_attachments', '_decode_node'):
        wrap(codec, name, name)


def recompute(muscle):
    from anthroforge.core.deps.runtime import run_dependency_runtime
    return str(run_dependency_runtime(root(), bpy.context.scene, dirty_hints={'MUSCLE': {muscle.id}}, full=False, quality='FINAL'))


def save_blend():
    if not STATE['args'].save_blend: return
    from anthroforge.adapters.authoring.scene import StaticScene
    StaticScene(root(), bpy.context.scene).save_debug_copy(STATE['args'].save_blend)


if __name__ == '__main__': main()
