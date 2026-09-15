"""Replay frozen prepared inputs in Blender; never union geometry or resnap pins."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fiber_roadmap_qualification as bench
from anthroforge.core.vcp.v2.contracts import decode_request, V2ColliderSnapshot
from anthroforge.core.vcp.v2.planner_search import RoadmapPolicy
from anthroforge.core.vcp.v2 import planner as p


def options():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--source', required=True); parser.add_argument('--run', type=int, default=0)
    parser.add_argument('--fibers', nargs='*'); parser.add_argument('--solver', action='store_true')
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def prepared_collider(collider, geometry):
    candidates = [r for r in geometry['before'] if r['owner'] == collider.owner_id
        and np.asarray(r['vertices']).shape == np.asarray(collider.vertices).shape
        and np.max(np.abs(np.asarray(r['vertices'])-collider.vertices)) < 1e-6]
    if not candidates: return collider
    assert len(candidates) == 1
    row = next(r for r in geometry['after'] if r['name'] == candidates[0]['name'])
    vertices = np.asarray(row['vertices']); triangles = np.asarray(row['triangles'], dtype=np.int32)
    generation = (bench.array_hash(vertices),); topology = (bench.array_hash(triangles),)
    return replace(collider, vertices=vertices, triangles=triangles, generation=('PIN_UNION', *generation),
                   geometry_generation=generation, topology_generation=topology)


def load_cases(config):
    root = Path(config.reference); geometry = read(root/'geometry.json')
    colliders = tuple(prepared_collider(V2ColliderSnapshot.from_payload(c), geometry)
                      for c in read(root/'original_world.json'))
    ids = config.fibers or [r['id'] for r in read(root/'inventory.json')]
    ids = ids if config.run == 0 else (list(reversed(ids)) if config.run == 1 else ids[25:]+ids[:25])
    return [(name, decode_request(dict(read(root/name/'union_request.json'), colliders=colliders_payload(colliders))))
            for name in ids]


def colliders_payload(colliders):
    from dataclasses import asdict
    return [asdict(collider) for collider in colliders]


def integrated_plan(request, recovery=True):
    session = p.begin_plan_reference_v43(request, policy=RoadmapPolicy(expanded=True, pin_recovery=recovery))
    while not session.done: session.step()
    return session.result


def run_one(request, mode, cold):
    tick = perf_counter()
    if cold: bench.production.clear_v3_caches()
    accepted = bench.accepted_v3_request(request, bench.production.V3_PRODUCTION_POLICY)
    result = integrated_plan(accepted, recovery=mode == 'INTEGRATED')
    elapsed = 1000*(perf_counter()-tick)
    validation = bench.audit(accepted, result.reference, result.pin_indices) if result.succeeded else None
    if validation is not None:
        assert validation['valid'] and max(validation['pin_residuals']) == 0.
        assert validation['count'] == request.settings.node_count
    return dict(mode=mode, cold=cold, elapsed_ms=elapsed, result=result, validation=validation)


def run_case(config, name, request, ordinal):
    expected = read(Path(config.reference)/name/'union.json')['stages']['SEARCH']['result']['reference']
    modes = ('ORDINARY', 'INTEGRATED') if (ordinal+config.run) % 2 == 0 else ('INTEGRATED', 'ORDINARY')
    rows = []
    for mode in modes:
        for cold in (True, False):
            row = run_one(request, mode, cold)
            if mode == 'INTEGRATED':
                assert row['result'].succeeded
                np.testing.assert_array_equal(row['result'].reference, expected)
            rows.append(row); print('PIN_RECOVERY', name, mode, cold, round(row['elapsed_ms'], 2), flush=True)
    bench.write(Path(config.output)/name/'timing.json', rows)
    if config.solver: solve_case(config, name, request)
    return dict(id=name, rows=rows)


def solve_case(config, name, request):
    session = bench.production.begin_v3(request, planner_policy=RoadmapPolicy(expanded=True, pin_recovery=True))
    tick = perf_counter()
    try:
        phases, slices, seed = bench.drain(session); result = session.package.result
        audit = bench.audit(session.request, result.points, session.pins)
        bench.write(Path(config.output)/name/'solver.json', dict(result=result, audit=audit, seed=seed,
            elapsed_ms=1000*(perf_counter()-tick), phases=phases, slices=slices))
    finally: session.cancel()


def main():
    config = options(); before = bench.digest(config.source); rows = load_cases(config)
    assert before == read(Path(config.reference)/'manifest.json')['sha256'], 'source differs from frozen qualification fixture'
    bench.write(Path(config.output)/'manifest.json', dict(**bench.manifest(config, before),
        reference=config.reference, code_hashes=code_hashes(), prepared_inputs=True, union_performed=False, resnap_performed=False,
        reference_mode='PRODUCTION_WITHOUT_PIN_RECOVERY', golden_source='FROZEN_ACCEPTED_PLANNER_POINTS',
        boundary='cache clear + policy + full planner setup/preflight/attempts/handoff; extra audit excluded'))
    results = [run_case(config, name, request, i) for i, (name, request) in enumerate(rows)]
    after = bench.digest(config.source)
    bench.write(Path(config.output)/'run.json', dict(fibers=results, before=before, after=after))
    assert before == after


def code_hashes():
    root = Path(__file__).resolve().parents[1]
    paths = list((root/'core/vcp/v2').glob('planner*.py'))
    paths += [Path(__file__), root/'native/fiber_ccd/af_fiber_ccd_v3_13.dll']
    return {str(path.relative_to(root)): bench.digest(path) for path in paths}


if __name__ == '__main__': main()
