"""Real foreground undo/redo of muscle bindings and complete tissue geometry."""
from pathlib import Path
import json
import sys
import traceback
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _free_probe_support import load, output_directory
ADDON = load()
import bpy
from _helpers import ensure_addon_registered, select_only
from test_muscle_parent_fibers import tissue_chain
OUTPUT = output_directory(); STATE = {}; REPORT = []


def owner():
    return bpy.data.objects[STATE['root']]


def snapshot():
    root = owner(); fiber = next(f for f in root.af_vcp_system.fibers if f.id == STATE['fiber'])
    curves = {o.name: json.loads(o['af_fiber_points_world']) for o in bpy.context.scene.objects if o.get('af_fiber_proxy') and o.get('af_fiber_points_world')}
    meshes = {o.name: [list(v.co) for v in o.data.vertices] for o in bpy.context.scene.objects if o.get('af_soft_tissue_proxy')}
    return dict(binding=fiber.node_attachments_json, free=fiber.free_path_json, supports=[s.target_id for s in fiber.attachment_supports], curves=curves, meshes=meshes)


def setup():
    ensure_addon_registered(); root, muscle, tissue, surface = tissue_chain('LAYER')
    fiber = next(f for f in root.af_vcp_system.fibers if f.behavior_mode == 'FREE')
    STATE.update(root=root.name, fiber=fiber.id, muscle=muscle.id)
    from _helpers import find_flagged
    from anthroforge.core.vcp.surface_reference import key, from_object
    STATE['target'] = key(from_object(surface))
    select_only(find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id')); bpy.context.preferences.edit.use_global_undo = True
    STATE['before'] = snapshot(); bpy.ops.ed.undo_push(message='Muscle attachment initial state')


def edit():
    from anthroforge.ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
    assert AF_PT_FiberEditPanel.poll(bpy.context)
    assert bpy.ops.af.fiber_attachment('EXEC_DEFAULT', True, action='ADD', fiber_id=STATE['fiber'],
        use_choice=True, surface_choice=STATE['target']) == {'FINISHED'}
    assert AF_PT_FiberEditPanel.poll(bpy.context)
    STATE['after'] = snapshot(); assert STATE['after']['supports']


def compare(expected):
    actual = snapshot()
    for key in ('binding', 'free', 'supports'): assert actual[key] == expected[key], key
    for key in ('curves', 'meshes'):
        assert actual[key].keys() == expected[key].keys(), key
        for name, points in actual[key].items(): np.testing.assert_allclose(points, expected[key][name], atol=1e-5)


def undo():
    bpy.ops.ed.undo(); compare(STATE['before'])


def redo():
    bpy.ops.ed.redo(); compare(STATE['after'])


def context_override():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def finish(passed, error=''):
    (OUTPUT/'ui_result.json').write_text(json.dumps(dict(passed=passed, steps=REPORT, error=error)), encoding='utf8')
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=.5)


STEPS = iter((setup, edit, undo, redo))


def tick():
    action = next(STEPS, None)
    if action is None: finish(True); return None
    try:
        with context_override(): action()
        REPORT.append(action.__name__); return .3
    except Exception:
        finish(False, traceback.format_exc()); return None


bpy.app.timers.register(tick, first_interval=1.)
