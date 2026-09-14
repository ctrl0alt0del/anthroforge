"""Verify paired qualification output and summarize explicit timing boundaries."""

import argparse
import json
from pathlib import Path
from statistics import median


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def untimed(value):
    if isinstance(value, dict):
        return {k: untimed(v) for k, v in value.items() if not k.endswith('_ms')}
    if isinstance(value, list): return [untimed(v) for v in value]
    return value


def verify_pair(folder, phase, cache, repeat):
    a = read(folder/f'{phase}_REFERENCE_{cache}_{repeat}.json')
    b = read(folder/f'{phase}_INTEGRATED_{cache}_{repeat}.json')
    assert a['graphs'] == b['graphs'], (folder.name, 'graph')
    assert a['validation'] == b['validation'], (folder.name, 'validation')
    if a['plan'] is not None:
        for field in ('reference', 'corridor', 'pin_indices', 'termination', 'failure_reason'):
            assert a['plan'][field] == b['plan'][field], (folder.name, field)
    if phase == 'solve':
        for field in ('points', 'termination', 'validated', 'route_branch'):
            assert a['result'][field] == b['result'][field], (folder.name, field)
        assert untimed(a['result']['diagnostics']) == untimed(b['result']['diagnostics']), folder.name
        assert a['seed'] == b['seed'], (folder.name, 'seed')


def verify_old(folder, original):
    if original is None or folder.name not in ('FIBER_170', 'FIBER_173', 'FIBER_174'): return
    a = read(folder/'solve_INTEGRATED_COLD_1.json')
    b = read(original/folder.name/'solve_COMBINED_1.json')
    assert a['result']['points'] == b['result']['points'], (folder.name, 'accepted experimental points')
    assert untimed(a['result']['diagnostics']) == untimed(b['result']['diagnostics']), (folder.name, 'diagnostics')


def row_summary(folder, phase, mode, cache):
    files = sorted(folder.glob(f'{phase}_{mode}_{cache}_*.json')); rows = [read(p) for p in files]
    values = [row['elapsed_ms'] for row in rows]; result = rows[0]['plan' if phase == 'plan' else 'result']
    return dict(fiber=folder.name, phase=phase, mode=mode, cache=cache, repeats=len(rows),
        median_ms=median(values), minimum_ms=min(values), maximum_ms=max(values),
        termination=result['termination'], validated=rows[0]['validation']['valid'],
        longest_slice_ms=max((s[1] for row in rows for s in row.get('slices', [])), default=0.))


def verify_directory(folder, original):
    rows = []
    for phase in ('plan', 'solve'):
        for cache in ('COLD', 'WARM'):
            for path in sorted(folder.glob(f'{phase}_INTEGRATED_{cache}_*.json')):
                verify_pair(folder, phase, cache, path.stem.split('_')[-1])
            for mode in ('BASE', 'REFERENCE', 'INTEGRATED'):
                if tuple(folder.glob(f'{phase}_{mode}_{cache}_*.json')):
                    rows.append(row_summary(folder, phase, mode, cache))
    if (folder/'solve_INTEGRATED_COLD_1.json').exists(): verify_old(folder, original)
    return rows


def source_hashes(root):
    rows = [read(p) for p in root.glob('hash_*.json')]
    assert rows and all(row['before'] == row['after'] == rows[0]['before'] for row in rows)
    return dict(processes=len(rows), sha256=rows[0]['before'])


def paired_replay(root):
    rows = []
    for fiber in ('FIBER_170', 'FIBER_173', 'FIBER_174'):
        old = [read(root/'paired_accepted'/f'{fiber}_{i}.json') for i in (1, 2, 3)]
        new = [read(root/'paired_integrated'/f'{fiber}_{i}.json') for i in (1, 2, 3)]
        for a, b in zip(old, new):
            assert a['result']['points'] == b['result']['points'], fiber
            assert untimed(a['result']['diagnostics']) == untimed(b['result']['diagnostics']), fiber
        before, after = median(r['elapsed_ms'] for r in old), median(r['elapsed_ms'] for r in new)
        assert after <= 1.1*before, (fiber, 'paired optimized-reference gate')
        rows.append(dict(fiber=fiber, accepted_ms=before, integrated_ms=after, change_percent=100*(after/before-1)))
    (root/'paired_comparison.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('directory', type=Path)
    parser.add_argument('--accepted', type=Path); parser.add_argument('--paired', type=Path); options = parser.parse_args()
    rows = [r for folder in sorted(options.directory.glob('FIBER_*')) for r in verify_directory(folder, options.accepted)]
    output = dict(source=source_hashes(options.directory), exact_paired_parity=True, rows=rows)
    if options.paired: output['paired_optimized_reference'] = paired_replay(options.paired)
    (options.directory/'verified_comparison.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    for row in rows:
        print(row['fiber'], row['phase'], row['cache'], row['mode'], round(row['median_ms'], 2), row['termination'])


if __name__ == '__main__': main()
