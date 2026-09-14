"""Test-only replay of captured requests against a frozen accepted experiment or production."""

import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter


def module_at(name, path, package=False):
    spec = importlib.util.spec_from_file_location(name, path,
        submodule_search_locations=[str(path.parent)] if package else None)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def arguments():
    parser = argparse.ArgumentParser(); parser.add_argument('--addon', type=Path, required=True)
    parser.add_argument('--experiment', type=Path); parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--repeat', type=int, required=True)
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def solve(production, request):
    tick = perf_counter(); session = production.begin_v3(request); phases = {}
    try:
        while not session.done:
            phase = session.phase; step = perf_counter(); session.step()
            phases[phase] = phases.get(phase, 0.)+1000*(perf_counter()-step)
        return dict(elapsed_ms=1000*(perf_counter()-tick), phases=phases, result=asdict(session.package.result))
    finally: session.cancel()


def main():
    options = arguments(); addon = options.addon.resolve(); module_at('anthroforge', addon/'__init__.py', True)
    from anthroforge.core.vcp.v2.contracts import V2Request
    from anthroforge.core.vcp.v2.collision import collision_backend_status
    from anthroforge.core.vcp.v3 import production
    experiment = module_at('accepted_replay', options.experiment.resolve()) if options.experiment else None
    assert collision_backend_status().available
    for identifier in ('FIBER_170', 'FIBER_173', 'FIBER_174'):
        payload = json.loads((options.captures/identifier/'capture_1.json').read_text())['request']
        request = V2Request.from_payload(payload); production.clear_v3_caches()
        if experiment: experiment.fast.library(); experiment.configure('COMBINED')
        row = solve(production, request); options.output.mkdir(parents=True, exist_ok=True)
        (options.output/f'{identifier}_{options.repeat}.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
        print(identifier, round(row['elapsed_ms'], 2), flush=True)


if __name__ == '__main__': main()
