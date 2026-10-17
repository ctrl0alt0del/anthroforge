"""Real Blender construction/deformation acceptance; input fixture is never overwritten."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / 'tests'), str(Path(__file__).parent)]
import anthroforge
from anthroforge.adapters.deformation import request, runtime, storage, jobs
from anthroforge.adapters.deformation.publication import mesh_identity
from anthroforge.adapters.authoring.scene import StaticScene
from fixtures.deformation_scene import debug_visibility


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', choices=['baseline', 'rebuild', 'arc5', 'pec2'], required=True)
    parser.add_argument('--method', choices=['LE', 'FAST'], default='LE')
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def change(root, case):
    from anthroforge.app.use_cases.shortcut_edit import apply_shortcut_value
    from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements
    if case == 'arc5':
        shortcut = next(s for s in root.af_shortcut_system.shortcuts if s.name == 'Ribs Arc Radius')
        assert apply_shortcut_value(bpy.context, shortcut, 5.)
    elif case == 'pec2':
        muscle = next(m for m in root.af_vcp_system.muscles if m.name == 'Pectoralis major.L fan')
        assert muscle.inflation_mode == 'SECTION_PROFILE'
        muscle.section_depths = tuple(2 * v for v in muscle.section_depths)
    drain_fiber_refinements()
    bpy.context.view_layer.update()


def deform(root):
    runtime.enqueue(root, bpy.context.scene, True)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        runtime.tick()
        if not runtime.QUEUE.slots and not jobs.ACTIVE:
            assert root.get('af_deformation_status') == 'Updated', root.get('af_deformation_status')
            return
        time.sleep(.1)
    raise TimeoutError('Deformation exceeded 30 minutes')


def rebuild():
    from anthroforge.app.use_cases import warm_update
    result = warm_update.start_update(bpy.context, 'FORCE_FULL')
    assert result.ok, result.message
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        status = warm_update.poll_update(bpy.context)
        if status.state in {'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED'}:
            result = warm_update.complete_update(bpy.context, status)
            assert status.state == 'SUCCEEDED' and result.ok, result.message
            return
        time.sleep(.25)
    raise TimeoutError('Full construction exceeded one hour')


def persisted(root, obj, path):
    before = mesh_identity(obj)
    signature = storage.load(root, obj).signature
    StaticScene(root, bpy.context.scene).save_debug_copy(path)
    bpy.ops.wm.open_mainfile(filepath=str(path))
    root = bpy.data.objects['AF_ROOT']
    obj = request.topology(root, bpy.context.scene)
    assert storage.load(root, obj).signature == signature
    assert all(np.array_equal(a, b) for a, b in zip(before, mesh_identity(obj)))
    assert not any(o.get('af_draft_skin') for o in bpy.context.scene.objects)
    return root, obj, debug_visibility(root)


def execute(options, root, before):
    started = time.monotonic()
    if options.case == 'rebuild':
        rebuild()
    elif options.case != 'baseline':
        change(root, options.case)
        deform(root)
    obj = request.topology(root, bpy.context.scene)
    after = mesh_identity(obj)
    if options.case != 'rebuild':
        assert np.array_equal(before[1], after[1]) and np.array_equal(before[2], after[2])
    result = dict(seconds=time.monotonic()-started, vertices=len(after[0]), quads=len(after[1]))
    result['statistics'] = json.loads(obj.get('af_topology_stats_json', '{}'))
    return obj, result


def run(options):
    anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(options.fixture.resolve()))
    root = bpy.data.objects['AF_ROOT']
    bpy.context.view_layer.objects.active = root; root.af_topology_settings.deformation_method = options.method
    root.af_topology_settings.symmetry_mode = 'Y'
    obj, report = execute(options, root, mesh_identity(request.topology(root, bpy.context.scene)))
    runtime.shutdown()
    options.output.mkdir(parents=True, exist_ok=True)
    root, obj, report['visibility'] = persisted(root, obj, options.output / 'debug.blend')
    report['fixture_sha256'] = hashlib.sha256(options.fixture.read_bytes()).hexdigest()
    (options.output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    from torso_views import render_views
    render_views(obj, options.output)
    print('TORSO_VALIDATED', json.dumps({k:v for k,v in report.items() if k != 'statistics'}), flush=True)


if __name__ == '__main__':
    try:
        run(arguments())
    finally:
        runtime.shutdown()
        from anthroforge.adapters.warm_update.jobs import shutdown_jobs
        shutdown_jobs()
