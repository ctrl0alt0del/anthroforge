"""Read-only Blender qualification of production snapping on frozen finger surfaces.

Replays the already unioned geometry from the accepted fixture. Does NOT union
or repair source geometry. Tests real surface capture and the production fallback.
"""
import argparse
from dataclasses import replace
from pathlib import Path
from time import perf_counter
import sys
import bpy
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_roadmap_qualification as bench
from fiber_pin_recovery_foreground import replay_meshes
from fiber_pin_recovery_qualification import read
from anthroforge.core.vcp import attachment_backend as backend, fiber_pin_snapping as snapping
from anthroforge.core.vcp.v2 import planner
from anthroforge.core.vcp.v2.contracts import V2Anchor, V2Request
from mathutils import Vector


def options():
    parser = argparse.ArgumentParser()
    for name in ('source', 'reference', 'output'): parser.add_argument('--'+name, required=True)
    parser.add_argument('--fibers', nargs='*'); parser.add_argument('--planner', action='store_true')
    parser.add_argument('--profile', action='store_true')
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def snap_pin(root, scene, runtime, pin, radius):
    anchor = pin['old']; owner = anchor['owner_id']; tick = perf_counter()
    raw = snapping.capture_attachment_from_world(root, scene, owner, Vector(anchor['point']), runtime,
                                                  radius, pin.get('offset', 0.))
    elapsed = 1000*(perf_counter()-tick); result = runtime['pin_snap_last_result']
    error = None if not raw else float(np.linalg.norm(np.asarray(result.point)-pin['new']))
    return dict(result=result, full_ms=elapsed, reference_error=error, role=anchor['role'], owner=owner)


def test_fiber(config, root, runtime, identifier):
    record = read(Path(config.reference)/identifier/'union.json'); rows = []
    radius = next(f.collision_radius for f in root.af_vcp_system.fibers if f.id == identifier)
    for pin in record['pins']:
        if 'old' not in pin: continue
        rows.append(snap_pin(root, bpy.context.scene, runtime, pin, radius))
    output = dict(id=identifier, pins=rows, valid=all(r['result'].valid for r in rows))
    if config.planner and output['valid']: output.update(check_planner(config, root, runtime, identifier, rows))
    bench.write(Path(config.output)/(identifier+'.json'), output)
    print(identifier, output['valid'], sum(r['full_ms'] for r in rows), flush=True)
    return output


def check_planner(config, root, runtime, identifier, rows):
    payload = read(Path(config.reference)/identifier/'union_request.json')
    request = snapping._request(root, bpy.context.scene, runtime, payload['collision_policy']['collision_radius'])
    pins = iter(rows); anchors = []
    for old in payload['anchors']:
        row = next(pins) if old['owner_id'] in {f'SCP_{i}' for i in range(17, 22)} else None
        anchors.append(V2Anchor(tuple(row['result'].point) if row else tuple(old['point']), old['owner_id'], old['role'], old['authored_index']))
    prepared = V2Request.from_payload({**payload, 'colliders': []})
    prepared = replace(prepared, colliders=request.colliders, tolerances=request.tolerances, anchors=tuple(anchors))
    tick = perf_counter(); result = planner.plan_reference_v43(prepared)
    return dict(planner=result, planner_ms=1000*(perf_counter()-tick))


def main():
    config = options(); before = bench.digest(config.source); roots = bench.setup(config.source)
    replay_meshes(Path(config.reference)); root = roots[0]
    runtime = backend.attachment_runtime(bpy.context.scene)
    ids = config.fibers or [r['id'] for r in read(Path(config.reference)/'inventory.json')]
    rows = run_cases(config, root, runtime, ids)
    after = bench.digest(config.source); assert before == after
    values = [p['full_ms'] for r in rows for p in r['pins']]
    bench.write(Path(config.output)/'summary.json', dict(before=before, after=after, fibers=len(rows),
        valid=sum(r['valid'] for r in rows), pins=len(values), timings=np.percentile(values, [0, 50, 95, 99, 100])))


def run_cases(config, root, runtime, ids):
    import cProfile
    import pstats
    profiler = cProfile.Profile()
    if config.profile: profiler.enable()
    rows = [test_fiber(config, root, runtime, name) for name in ids]
    if config.profile:
        profiler.disable(); profiler.dump_stats(str(Path(config.output)/'profile.pstats'))
        pstats.Stats(profiler).strip_dirs().sort_stats('cumulative').print_stats(35)
    return rows


if __name__ == '__main__': main()
