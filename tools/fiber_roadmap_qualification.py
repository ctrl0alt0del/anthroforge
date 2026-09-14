"""Read-only three-way production roadmap qualification in real Blender processes."""

import argparse
from dataclasses import asdict, is_dataclass, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent), str(ROOT)]
from anthroforge.core.vcp.v2 import planner as planner
from anthroforge.core.vcp.v2.planner_search import RoadmapPolicy
from anthroforge.core.vcp.v2.planner_preparation import graph_csr
from anthroforge.core.vcp.v3 import production, solver
from anthroforge.core.vcp.v3.policy import accepted_v3_request
from tests.roadmap_reference import ReferenceRoadmapPreparation

FIBERS = ('FIBER_170', 'FIBER_173', 'FIBER_174', 'FIBER_128', 'FIBER_181',
          'FIBER_154', 'FIBER_155', 'FIBER_156', 'FIBER_162', 'FIBER_321')


def plain(value):
    if is_dataclass(value): return asdict(value)
    if isinstance(value, Enum): return value.value
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    raise TypeError(type(value).__name__)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, default=plain, indent=2), encoding='utf-8')


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--repeat', type=int, default=1); parser.add_argument('--fibers', nargs='+', default=FIBERS)
    parser.add_argument('--solver', action='store_true'); parser.add_argument('--export', action='store_true')
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def setup(source):
    import anthroforge
    if not hasattr(bpy.types.Object, 'af_vcp_system'): anthroforge.register()
    bpy.ops.wm.open_mainfile(filepath=str(source))
    from anthroforge.core.visualization import sync_runner
    for _ in range(12):
        bpy.context.view_layer.update()
        if not sync_runner._PENDING and not sync_runner._TAIL_PENDING: break
        for item in sync_runner._PENDING: item.due_at = 0
        sync_runner._flush_pending()
    return [obj for obj in bpy.context.scene.objects if obj.get('anthroforge_root')]


def capture(roots, identifier):
    from anthroforge.core.visualization.fiber_refinement import _prepared_session
    from anthroforge.core.vcp.fiber_v2_runtime import _capture_one, _request
    root, fiber = next((r, f) for r in roots for f in r.af_vcp_system.fibers if f.id == identifier)
    tick = perf_counter(); runtime = _prepared_session(root, bpy.context.scene, fiber, 'FINAL')
    while not runtime.done and runtime.capture_index < len(runtime.source_colliders): _capture_one(runtime)
    if runtime.done: raise RuntimeError(runtime.invalid_reason or runtime.runtime_error)
    request = _request(runtime); runtime.cancel()
    return replace(request, warm_seed=()), 1000*(perf_counter()-tick)


def array_hash(values):
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def graph_record(output, span, points, graph, checked):
    offsets, links = graph_csr(graph); final_offsets, final_links = graph_csr(checked)
    output.append(dict(span=span, points=array_hash(np.asarray(points)), offsets=array_hash(offsets),
        links=array_hash(links), checked_offsets=array_hash(final_offsets), checked_links=array_hash(final_links)))


def policy_for(mode, graphs):
    reference = ReferenceRoadmapPreparation(planner) if mode == 'REFERENCE' else None
    observer = None if graphs is None else lambda *args: graph_record(graphs, *args)
    return RoadmapPolicy(mode != 'BASE', reference, observer)


def graph_audit(request, mode, expected):
    if expected is None or not expected.diagnostics.recoveries: return []
    graphs = []; result = planner.plan_reference_v43(request, policy=policy_for(mode, graphs))
    assert result.reference == expected.reference and result.termination == expected.termination
    return graphs


def audit(request, points, pins):
    if not len(points): return dict(valid=False, bad_edges=[], count=0)
    values = np.asarray(points); cyclic = planner._cyclic(request)
    edges = solver._validation_edges(len(values), cyclic); owners = solver._edge_owners(request, pins, edges)
    from types import SimpleNamespace
    session = SimpleNamespace(request=request, pins=pins, cyclic=cyclic)
    world = planner.cached_native_collision_world(request.colliders)
    checked = world.validate(values, edges, owners, solver._owner_span(session, values), solver._threshold(session))
    return dict(valid=all(checked.clear), finite=bool(np.isfinite(values).all()), count=len(values),
        pin_residuals=[float(np.linalg.norm(values[i]-a.point)) for i, a in zip(pins, request.anchors)],
        bad_edges=[(i, b) for i, (c, b) in enumerate(zip(checked.clear, checked.blockers)) if not c])


def plan_run(request, mode, cache):
    if cache == 'COLD': production.clear_v3_caches()
    policy = policy_for(mode, None); accepted = accepted_v3_request(request, production.V3_PRODUCTION_POLICY)
    tick = perf_counter(); result = planner.plan_reference_v43(accepted, policy=policy)
    elapsed = 1000*(perf_counter()-tick)
    graphs = graph_audit(accepted, mode, result)
    return dict(mode=mode, cache=cache, elapsed_ms=elapsed, plan=result, graphs=graphs,
        validation=audit(accepted, result.reference, result.pin_indices))


def drain(session):
    tick = perf_counter(); phases = {}; slices = []; seed = None
    while not session.done:
        phase = session.phase; step = perf_counter(); session.step(); duration = 1000*(perf_counter()-step)
        phases[phase] = phases.get(phase, 0.)+duration; slices.append((phase, duration))
        if phase == 'PLAN' and session.phase != 'PLAN': seed = session.seed.copy()
        if perf_counter()-tick > 90: session.cancel(); raise TimeoutError('90 second diagnostic deadline')
    return phases, slices, seed


def solve_run(request, mode, cache, warm=()):
    if cache == 'COLD': production.clear_v3_caches()
    policy = policy_for(mode, None); request = replace(request, warm_seed=tuple(map(tuple, warm)))
    tick = perf_counter(); session = production.begin_v3(request, planner_policy=policy)
    try:
        assert session.request.settings.fidelity_weight == request.settings.fidelity_weight*.01
        phases, slices, seed = drain(session); elapsed = 1000*(perf_counter()-tick); result = session.package.result
        graphs = graph_audit(session.request, mode, session.planner)
        return dict(mode=mode, cache=cache, elapsed_ms=elapsed, phases=phases, slices=slices, seed=seed,
            plan=session.planner, graphs=graphs, result=result, trace=session.package.trace,
            validation=audit(session.request, result.points, session.pins))
    finally: session.cancel()


def run_case(request, identifier, options):
    modes = ('BASE', 'REFERENCE', 'INTEGRATED'); shift = options.repeat % 3; rows = []
    for mode in modes[shift:]+modes[:shift]:
        for cache in ('COLD', 'WARM'):
            row = plan_run(request, mode, cache); save_row(row, 'plan', identifier, options)
        if options.solver:
            cold = solve_run(request, mode, 'COLD'); save_row(cold, 'solve', identifier, options); rows.append(cold)
            warm = solve_run(request, mode, 'WARM', cold['result'].points); save_row(warm, 'solve', identifier, options)
    return rows


def save_row(row, phase, identifier, options):
    path = Path(options.output)/identifier/f'{phase}_{row["mode"]}_{row["cache"]}_{options.repeat}.json'
    write(path, row); result = row.get('result', row.get('plan'))
    print(phase, identifier, row['mode'], row['cache'], round(row['elapsed_ms'], 2),
          result.termination.value, row['validation']['valid'], flush=True)


def export_geometry(request, identifier, rows, options):
    if not options.export or not rows: return
    colliders = [c for c in request.colliders if c.owner_id in {f'SCP_{i}' for i in range(16, 22)}]
    write(Path(options.output)/identifier/'visual.json', dict(colliders=colliders, anchors=request.anchors,
        radius=request.collision_policy.collision_radius, results=rows))


def manifest(options, before):
    from anthroforge.core.vcp.v2.collision_native import native_path
    return dict(source=options.source, sha256=before, blender=bpy.app.version_string,
        commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        os=platform.platform(), cpu=platform.processor(), engine=production.V3_PRODUCTION_VERSION,
        backend_sha256=digest(native_path()), arguments=sys.argv, background=bpy.app.background,
        environment={k: v for k, v in os.environ.items() if k.startswith(('AF_FIBER', 'OMP'))},
        timing_boundary='Planner call / numeric begin-to-done. Excludes capture, audit, commit, downstream.',
        loader='Numeric caches cleared for COLD; DLL load may occur during capture and is not forced cold.')


def main():
    options = arguments(); before = digest(options.source); roots = setup(options.source)
    write(Path(options.output)/f'manifest_{options.repeat}.json', manifest(options, before))
    for identifier in options.fibers:
        request, elapsed = capture(roots, identifier)
        write(Path(options.output)/identifier/f'capture_{options.repeat}.json', dict(request=request, capture_ms=elapsed))
        rows = run_case(request, identifier, options); export_geometry(request, identifier, rows, options)
    after = digest(options.source); write(Path(options.output)/f'hash_{options.repeat}.json', dict(before=before, after=after))
    assert before == after, 'source blend changed'


if __name__ == '__main__': main()
