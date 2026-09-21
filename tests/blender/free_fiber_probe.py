"""Run in disposable background Blender; emit geometry, save/reopen and timings."""
from pathlib import Path
import json
import sys
from time import perf_counter
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _free_probe_support import load, output_directory
ADDON = load()
import bpy
import numpy as np
from mathutils import Vector
from _helpers import reset_scene
from _branch_fixture import create_fixture
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.adapters import free_fiber_editor as editor
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request
from anthroforge.core.vcp.branched_numeric import evaluate
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp import free_path

OUTPUT = output_directory()


def timed(action):
    start = perf_counter(); value = action()
    return value, (perf_counter() - start) * 1000


def measure(count):
    reset_scene(); owner, surface, fiber, _old = fixture()
    u = np.linspace(0, 1, count); points = np.column_stack((.1 + .6*u, .1 + .03*np.sin(2*np.pi*u), .2*np.sin(np.pi*u)))
    payload = service.payload_for_points(owner, bpy.context.scene, fiber, points, [0, count-1])
    _proxy, capture_ms = timed(lambda: service.commit(owner, bpy.context.scene, fiber, payload, points))
    rows = []
    for index in range(6): rows.append(_measure_edit(owner, surface, fiber, index))
    names = ('open_ms', 'sampling_ms', 'apply_ms', 'deform_ms')
    warm = np.asarray(rows[1:])
    return dict(samples=count, initial_capture_ms=capture_ms, cold=dict(zip(names, rows[0])),
                warm_median=dict(zip(names, np.median(warm, axis=0))), warm_p95=dict(zip(names, np.percentile(warm, 95, axis=0))), raw=rows)


def _measure_edit(owner, surface, fiber, index):
    objects, opened = timed(lambda: editor.open_edit(owner, bpy.context.scene, fiber))
    objects[0].data.splines[0].points[len(objects[0].data.splines[0].points)//2].co.z += .001
    _sample, sampled = timed(lambda: editor._sample_draft(editor.draft(owner, fiber), fiber.free_sampling_resolution))
    _result, applied = timed(lambda: editor.apply(owner, bpy.context.scene, fiber))
    surface.location.z = .05 * (index + 1); bpy.context.view_layer.update()
    outcome, deformed = timed(lambda: runtime.update(owner, bpy.context.scene, fiber))
    assert outcome[0], outcome[1]
    return opened, sampled, applied, deformed


def build_debug():
    reset_scene(); root, muscle, _connection, fibers = create_fixture()
    for fiber in fibers: service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
    with suppress_vcp_prop_updates():
        scp = root.af_scp_system.scps[0]; scp.mirror_enabled = True; scp.mirror_origin = (-3., 0., 0.)
    service.rebuild(root, bpy.context.scene, {f.id for f in fibers})
    expected = snapshot(root, muscle)
    editor.open_edit(root, bpy.context.scene, fibers[0]); editor.objects(editor.state(root, fibers[0]))[0].data.splines[0].points[1].co.y -= .1
    StaticScene(root, bpy.context.scene).save_debug_copy(OUTPUT / 'af24_recovery.blend')
    return root.name, muscle.id, fibers[0].id, expected


def snapshot(root, muscle):
    routes = {f.id: [list(p) for p in runtime.current(root, bpy.context.scene, f)[1]] for f in root.af_vcp_system.fibers}
    request = _branched_request(root, bpy.context.scene, muscle); result = evaluate(request, 'NATIVE')
    assert not result.error, result.error
    return dict(routes=routes, base=result.base_vertices.tolist(), inflated=result.inflated_vertices.tolist(),
                faces=result.faces.tolist(), display_curves=display_curves(root), anchors=anchors(root))


def display_curves(root):
    return [dict(name=o.name, fiber_id=o.get('af_fiber_id'), mirror=bool(o.get('af_fiber_mirror_proxy')),
                 points=[list(o.matrix_world @ p.co.xyz) for p in o.data.splines[0].points], color=list(o.color))
            for o in bpy.context.scene.objects if o.get('af_root_name') == root.name and o.get('af_fiber_proxy')]


def anchors(root):
    return {f.id: dict(indices=list(free_path.tagged_indices(free_path.decode(f.free_path_json))),
                      point_ids=[r['point_id'] for r in free_path.decode(f.free_path_json)['structural']])
            for f in root.af_vcp_system.fibers}


def reopen_debug(identity):
    name, muscle_id, fiber_id, before = identity
    with patch('anthroforge.core.visualization.fiber_refinement.begin_fiber_solve', side_effect=AssertionError('Free load solver')):
        bpy.ops.wm.open_mainfile(filepath=str(OUTPUT / 'af24_recovery.blend'))
    root = bpy.data.objects[name]; fibers = {f.id: f for f in root.af_vcp_system.fibers}
    session = editor.state(root, fibers[fiber_id]); assert session and session['stale']
    assert abs(editor.objects(session)[0].data.splines[0].points[1].co.y - (session['opening'][1][1] - .1)) < 1e-5
    editor.cancel(root, fibers[fiber_id]); muscle = next(m for m in root.af_vcp_system.muscles if m.id == muscle_id)
    after = snapshot(root, muscle); compare_snapshots(before, after); visibility(root)
    StaticScene(root, bpy.context.scene).save_debug_copy(OUTPUT / 'af24_free_paths.blend')
    (OUTPUT / 'saved_geometry.json').write_text(json.dumps(after), encoding='utf8')
    np.savez_compressed(OUTPUT / 'saved_geometry.npz', base=after['base'], inflated=after['inflated'], faces=after['faces'])


def compare_snapshots(before, after):
    for key in ('base', 'inflated'): np.testing.assert_allclose(before[key], after[key], atol=1e-6)
    for key, points in before['routes'].items(): np.testing.assert_allclose(points, after['routes'][key], atol=1e-6)
    assert before['faces'] == after['faces']


def visibility(root):
    curves = [o for o in bpy.context.scene.objects if o.get('af_root_name') == root.name and o.get('af_fiber_proxy')]
    assert len(curves) == 8 and sum(bool(o.get('af_fiber_mirror_proxy')) for o in curves) == 4
    assert all(o.type == 'CURVE' and not o.hide_get() and not o.hide_viewport for o in curves)
    assert not any(o.get('af_free_editor_session') for o in bpy.data.objects)
    (OUTPUT / 'reopen_visibility.json').write_text(json.dumps([dict(name=o.name, mirror=bool(o.get('af_fiber_mirror_proxy')), color=list(o.color)) for o in curves]), encoding='utf8')


def mixed_measurement():
    reset_scene(); root, muscle, _connection, fibers = create_fixture()
    for fiber in (fibers[0], fibers[2]): service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
    rows = [_measure_mixed(root, muscle, fibers) for _ in range(6)]; warm = np.asarray(rows[1:])
    names = ('capture_ms', 'native_evaluate_ms', 'rebuild_ms', 'budget_reject_ms')
    result = evaluate(_branched_request(root, bpy.context.scene, muscle), 'NATIVE')
    return dict(free=2, controlled=2, base_vertices=len(result.base_vertices), base_faces=len(result.faces),
                cold=dict(zip(names, rows[0])), warm_median=dict(zip(names, np.median(warm, axis=0))),
                warm_p95=dict(zip(names, np.percentile(warm, 95, axis=0))), raw=rows)


def _measure_mixed(root, muscle, fibers):
    request, capture_ms = timed(lambda: _branched_request(root, bpy.context.scene, muscle))
    result, native_ms = timed(lambda: evaluate(request, 'NATIVE')); assert not result.error
    _value, rebuild_ms = timed(lambda: service.rebuild(root, bpy.context.scene, {f.id for f in fibers}))
    _value, reject_ms = timed(lambda: reject_budget(root, muscle))
    return capture_ms, native_ms, rebuild_ms, reject_ms


def reject_budget(root, muscle):
    with patch('anthroforge.core.vcp.free_surface.MAX_VERTICES', 2):
        try: _branched_request(root, bpy.context.scene, muscle)
        except ValueError as error:
            assert 'FREE_OUTPUT_BUDGET' in str(error); return
    raise AssertionError('Missing preallocation rejection')


results = [measure(count) for count in (32, 64, 256, 512, 4096)]
(OUTPUT / 'performance.json').write_text(json.dumps(results, indent=2), encoding='utf8')
(OUTPUT / 'performance_mixed.json').write_text(json.dumps(mixed_measurement(), indent=2), encoding='utf8')
reopen_debug(build_debug())
print('AF24_FREE_PROBE_OK', flush=True)
