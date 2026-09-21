"""Disposable foreground Blender validates native Edit Mode and real undo/redo."""
from pathlib import Path
import json
import sys
import traceback
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _free_probe_support import load, output_directory
ADDON = load()
import bpy
from _helpers import select_only, ensure_addon_registered
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.adapters import free_fiber_editor as editor
from anthroforge.core.vcp import free_path

OUTPUT = output_directory(); STATE = {}; REPORT = []


def items():
    root = bpy.data.objects[STATE['root']]
    return root, next(f for f in root.af_vcp_system.fibers if f.id == STATE['fiber'])


def setup():
    ensure_addon_registered()
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    root, _surface, fiber, _points = fixture()
    service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
    root.af_scp_system.active_scp_index = 0; root.af_vcp_system.active_vcp_id = ''
    select_only(next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')))
    STATE.update(root=root.name, fiber=fiber.id, initial=fiber.free_path_json)
    assert_panel_available()
    bpy.context.preferences.edit.use_global_undo = True
    bpy.ops.ed.undo_push(message='AF24 Initial committed path')


def open_native():
    assert bpy.ops.af.free_fiber_path('EXEC_DEFAULT', True, fiber_id=STATE['fiber'], action='EDIT') == {'FINISHED'}
    assert bpy.context.object.mode == 'EDIT'
    assert_panel_available()


def assert_panel_available():
    from anthroforge.ui.panels.fiber_edit_panel import AF_PT_FiberEditPanel
    from anthroforge.app.queries.vcp import active_fiber_from_context
    assert AF_PT_FiberEditPanel.poll(bpy.context), 'Fiber panel disappeared after direct source/draft selection'
    assert active_fiber_from_context(bpy.context).id == STATE['fiber'], 'Fiber panel resolves another tree item'


def subdivide():
    bpy.ops.curve.select_all(action='SELECT'); bpy.ops.curve.subdivide('EXEC_DEFAULT', True, number_cuts=1)
    bpy.context.object.update_from_editmode()
    assert len(bpy.context.object.data.splines[0].points) == 7
    STATE['subdivided'] = [list(p.co) for p in bpy.context.object.data.splines[0].points]


def undo_draft():
    bpy.ops.ed.undo()
    assert bpy.context.object.mode == 'EDIT'; bpy.context.object.update_from_editmode()
    assert len(bpy.context.object.data.splines[0].points) == 4
    root, fiber = items(); assert fiber.free_path_json == STATE['initial']
    np.testing.assert_allclose([list(p.co[:3]) for p in bpy.context.object.data.splines[0].points], editor.state(root, fiber)['opening'], atol=1e-6)


def redo_draft():
    bpy.ops.ed.redo(); bpy.context.object.update_from_editmode()
    assert len(bpy.context.object.data.splines[0].points) == 7
    np.testing.assert_array_equal([list(p.co) for p in bpy.context.object.data.splines[0].points], STATE['subdivided'])


def move_interior():
    assert bpy.ops.af.free_fiber_path('EXEC_DEFAULT', True, fiber_id=STATE['fiber'], action='REBASE') == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT'); spline = bpy.context.object.data.splines[0]
    for point in spline.points: point.select = False
    spline.points[3].select = True
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.transform.translate('EXEC_DEFAULT', True, value=(0, 0, .15))


def apply_native():
    assert bpy.ops.af.free_fiber_path('EXEC_DEFAULT', True, fiber_id=STATE['fiber'], action='APPLY') == {'FINISHED'}
    root, fiber = items(); STATE['applied'] = fiber.free_path_json
    assert not editor.state(root, fiber); assert fiber.free_path_json != STATE['initial']
    assert len(free_path.decode(fiber.free_path_json)['samples']) == 7


def undo_apply():
    bpy.ops.ed.undo(); root, fiber = items()
    assert fiber.free_path_json == STATE['initial'], 'Apply must undo as one commit'
    assert editor.state(root, fiber), 'Undo must restore recoverable draft ownership'


def redo_apply():
    bpy.ops.ed.redo(); root, fiber = items()
    assert fiber.free_path_json == STATE['applied']; assert not editor.state(root, fiber)
    assert not any(o.get('af_free_editor_session') for o in bpy.data.objects)


def branch_snapshot():
    from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request
    from anthroforge.core.vcp.branched_numeric import evaluate
    from anthroforge.core.visualization.free_fiber_runtime import current
    root, _fiber = items(); muscle = next(m for m in root.af_vcp_system.muscles if m.id == STATE['muscle'])
    result = evaluate(_branched_request(root, bpy.context.scene, muscle), 'NATIVE'); assert not result.error, result.error
    return dict(base=result.base_vertices.tolist(), inflated=result.inflated_vertices.tolist(),
                routes={f.id: [list(p) for p in current(root, bpy.context.scene, f)[1]] for f in root.af_vcp_system.fibers})


def setup_branch():
    from _branch_fixture import create_fixture
    root, muscle, connection, fibers = create_fixture()
    for fiber in fibers: service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
    STATE.update(muscle=muscle.id, junction=connection.roots[0].point_id)
    STATE['branch_before'] = branch_snapshot()
    bpy.utils.register_class(AF_OT_AF24SharedEdit)
    bpy.ops.ed.undo_push(message='AF24 Shared branch baseline')


class AF_OT_AF24SharedEdit(bpy.types.Operator):
    bl_idname = 'af.af24_shared_edit'
    bl_label = 'AF24 Shared point edit probe'
    bl_options = {'UNDO'}

    def execute(self, context):
        root, _fiber = items()
        next(p for p in root.af_vcp_system.authored_points if p.id == STATE['junction']).normal_offset += .05
        return {'FINISHED'}


def shared_edit():
    assert bpy.ops.af.af24_shared_edit('EXEC_DEFAULT', True) == {'FINISHED'}
    STATE['branch_after'] = branch_snapshot()
    assert STATE['branch_after']['routes'] != STATE['branch_before']['routes']
    assert STATE['branch_after']['base'] != STATE['branch_before']['base']


def compare_branch(expected):
    current = branch_snapshot()
    for field in ('base', 'inflated'): np.testing.assert_allclose(current[field], expected[field], atol=1e-6)
    for key, rows in expected['routes'].items(): np.testing.assert_allclose(current['routes'][key], rows, atol=1e-6)


def undo_shared():
    bpy.ops.ed.undo(); compare_branch(STATE['branch_before'])


def redo_shared():
    bpy.ops.ed.redo(); compare_branch(STATE['branch_after'])


STEPS = iter((setup, open_native, subdivide, undo_draft, redo_draft, move_interior, apply_native, undo_apply, redo_apply,
              setup_branch, shared_edit, undo_shared, redo_shared))


def audit_step(name):
    root, fiber = items(); session = editor.state(root, fiber)
    return dict(step=name, mode=bpy.context.object.mode if bpy.context.object else None,
                committed=free_path.decode(fiber.free_path_json), draft=editor.draft(root, fiber) if session else None)


def context_override():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def shutdown():
    bpy.ops.wm.quit_blender()
    return None


def tick():
    action = next(STEPS, None)
    try:
        if action is None:
            (OUTPUT / 'ui_result.json').write_text(json.dumps(dict(passed=True, steps=REPORT)), encoding='utf8')
            print('AF24_FREE_UI_PROBE_OK', flush=True); bpy.app.timers.register(shutdown, first_interval=.5); return None
        with context_override(): action()
        with context_override(): REPORT.append(audit_step(action.__name__))
        return .3
    except Exception:
        (OUTPUT / 'ui_result.json').write_text(json.dumps(dict(passed=False, steps=REPORT, failed=action.__name__, traceback=traceback.format_exc())), encoding='utf8')
        traceback.print_exc(); bpy.app.timers.register(shutdown, first_interval=.5); return None


bpy.app.timers.register(tick, first_interval=1.)
