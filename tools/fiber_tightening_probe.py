"""Read a saved body; measure tightening on leg fibers without publishing or saving."""
import json
import sys
from pathlib import Path
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import anthroforge
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.vcp.free_path import tagged_indices
from anthroforge.core.vcp.attachment_backend import attachment_runtime
from anthroforge.core.vcp.attachment_surface import support_keys
from anthroforge.core.vcp.fiber_pin_snapping import snap_request
from anthroforge.core.vcp.v3.tightening import tighten


def capture(owner, fiber):
    context = attachment_runtime(bpy.context.scene); context['supports'] = support_keys(fiber)
    payload, points = runtime.current(owner, bpy.context.scene, fiber, context)
    request = snap_request(owner, bpy.context.scene, context, fiber.collision_radius)
    owners = [b['parent_id'] for b in runtime.bindings(fiber)]
    return request, np.asarray(points), tagged_indices(payload), owners


def measure(owner, fiber):
    request, points, pins, owners = capture(owner, fiber)
    row = dict(id=fiber.id, name=fiber.name, points=points.tolist(), pins=pins, runs=[])
    length = np.linalg.norm(np.diff(points, axis=0), axis=1).sum()
    for steps, limit in ((1, None), (2, None), (4, None), (8, None), (1, .005*length), (4, .005*length), (1, .01*length)):
        run = dict(steps=steps, limit=limit)
        try:
            after, report = tighten(request, points, pins, owners, accepted_steps=steps, max_displacement=limit)
            run.update(report, points=after.tolist())
        except (ValueError, RuntimeError) as error: run['error'] = str(error)
        row['runs'].append(run); print('TIGHTEN', fiber.name, {k:v for k,v in run.items() if k not in ('points', 'spans')}, flush=True)
    return row


def main():
    if not hasattr(bpy.types.Object, 'af_vcp_system'): anthroforge.register()
    scene_path = sys.argv[sys.argv.index('--')+1]; bpy.ops.wm.open_mainfile(filepath=scene_path)
    owner = next(o for o in bpy.context.scene.objects if len(o.af_vcp_system.muscles))
    chosen = []; names = ('Gastrocnemius', 'Tibialis', 'Sartorius', 'Semitendinosus', 'Rectus femoris')
    for name in names:
        fibers = [f for f in owner.af_vcp_system.fibers if name.casefold() in f.name.casefold() and f.behavior_mode == 'FREE']
        print('MATCH', name, [(f.id, f.name) for f in fibers], flush=True)
        if fibers: chosen.append(fibers[len(fibers)//2])
    result = [measure(owner, f) for f in chosen]
    target = ROOT / '.artifacts/tightening/probe.json'; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result), encoding='utf-8')
    print('TIGHTENING_PROBE_DONE', target, flush=True)


if __name__ == '__main__': main()
