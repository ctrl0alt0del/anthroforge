"""Profile shortcut propagation and muscle rebuilding in Blender's real event loop.

Run: blender --factory-startup --addons anthroforge INPUT.blend --python THIS --
--output DIRECTORY --instrument none|stages|profile --repeats 3
Only in-memory geometry is edited. No blend is saved. JSON/log writing occurs
outside action timings. Run each instrumentation level in a fresh Blender.
"""
import argparse
from collections import Counter
import cProfile
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import pstats
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _muscle_rebuild_trace import RebuildTrace, write_json
from shortcut_performance_probe import pending
from anthroforge.core.deps import runtime_trace
from anthroforge.core.utils import get_af_root
from anthroforge.core.visualization import sync_runner


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    instrument_arguments(parser)
    parser.add_argument('--scenarios', default='shortcut,full')
    parser.add_argument('--shortcut', default='Pubis Arc Radius')
    parser.add_argument('--muscle', default='')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--baseline', type=float, default=10)
    parser.add_argument('--settle', type=float, default=5)
    return parser.parse_args(sys.argv[sys.argv.index('--')+1:])


def instrument_arguments(parser):
    parser.add_argument('--instrument', choices=('none', 'stages', 'profile'), default='stages')
    parser.add_argument('--profile-scope', choices=('action', 'settle', 'all'), default='all')
    parser.add_argument('--depsgraph-timing', action='store_true')
    parser.add_argument('--experiment', choices=('none', 'cache512', 'skip-disabled', 'skip-publication-full', 'skip-mirrors-full'), default='none')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    folder = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=folder, text=True).strip()
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=folder, text=True)
    return dict(checkout=str(folder), head=head, status=status)


def muscle_inventory(root):
    surfaces = {s.id: s for s in root.af_vcp_system.fiber_surfaces}
    rows = []
    for m in root.af_vcp_system.muscles:
        source = surfaces.get(m.fiber_surface_id) if m.surface_source_mode == 'FIBER_SURFACE' else m
        rows.append(dict(id=m.id, name=m.name, source=m.surface_source_mode, surface=m.fiber_surface_id,
                         construction=getattr(source, 'construction_mode', ''), inflation=m.inflation_mode,
                         envelope=m.envelope_sides, domain=m.output_domain_mode,
                         fibers=[r.fiber_id for r in getattr(source, 'fiber_refs', ())]))
    return rows


def mesh_snapshot():
    rows = []
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or not (obj.get('af_muscle_proxy') or obj.get('af_muscle_mirror_proxy')): continue
        data = np.empty(len(obj.data.vertices)*3, dtype=np.float32)
        obj.data.vertices.foreach_get('co', data)
        loops = np.empty(len(obj.data.loops), dtype=np.int32); obj.data.loops.foreach_get('vertex_index', loops)
        signature = hashlib.sha256(data.tobytes()+loops.tobytes()).hexdigest()
        rows.append(dict(name=obj.name, muscle=obj.get('af_muscle_id', obj.get('af_source_muscle_id', '')),
                         role=obj.get('af_muscle_surface', ''), vertices=len(data)//3, faces=len(obj.data.polygons),
                         finite=bool(np.isfinite(data).all()), state=obj.get('af_muscle_output_state', ''), digest=signature))
    return rows


def profile_rows(profiler):
    stats = pstats.Stats(profiler)
    return [dict(file=k[0], line=k[1], function=k[2], primitive_calls=v[0], calls=v[1],
                 self_ms=v[2]*1000, cumulative_ms=v[3]*1000,
                 callers=[dict(file=c[0], line=c[1], function=c[2], statistics=x) for c,x in v[4].items()])
            for k,v in sorted(stats.stats.items(), key=lambda item: -item[1][3])]


def experiment(kind):
    """Diagnostic-only changes; every result must be compared with the baseline."""
    from anthroforge.core.vcp import muscle_profile_cache, free_muscle_numeric
    if kind == 'cache512':
        muscle_profile_cache.MAX_ENTRIES = 512
    if kind == 'skip-disabled':
        original = free_muscle_numeric._native
        def skip_disabled(grid, spec):
            return np.array(grid, copy=True) if not spec.inflation_enabled else original(grid, spec)
        free_muscle_numeric._native = skip_disabled


def change_muscle(root, key, index):
    muscle = next(m for m in root.af_vcp_system.muscles if key in (m.id, m.name))
    factor = 1.01 if index % 2 == 0 else 1/1.01
    if muscle.inflation_mode == 'SECTION_PROFILE':
        muscle.section_depths = tuple(float(x)*factor for x in muscle.section_depths)
    else: muscle.inflation_max_value *= factor


def cache_state():
    from anthroforge.core.vcp.muscle_profile_cache import CACHE, MAX_ENTRIES, MAX_BYTES
    return dict(entries=len(CACHE), bytes=sum(row[1] for row in CACHE.values()),
                max_entries=MAX_ENTRIES, max_bytes=MAX_BYTES)


def warning_state():
    from anthroforge.core.warnings.session import COORDINATOR, REPOSITORY
    return dict(metrics=dict(COORDINATOR.metrics), jobs=len(COORDINATOR.jobs),
                states=dict(Counter(row['status'] for row in REPOSITORY.states.values())))


def full_ablation(kind):
    from anthroforge.core.visualization import muscle_sync
    from anthroforge.core.deps import builtin_drivers
    if kind == 'skip-publication-full': return patch.object(muscle_sync, 'publish_muscle_work', side_effect=skip_publication)
    if kind == 'skip-mirrors-full': return patch.object(builtin_drivers, 'sync_vcp_mirrors', return_value=None)
    return nullcontext()


def skip_publication(sync, vis_col, root, scene, vcp, work, batch):
    assert all(w.request is not None and not w.error for w in work)
    assert all(not result.error for result in batch.results)
    return {w.muscle.id for w in work}


class Probe:
    def __init__(self, args):
        self.args, self.output = args, Path(args.output); self.output.mkdir(parents=True, exist_ok=True)
        self.root = get_af_root(bpy.context.scene)
        self.shortcut = next(s for s in self.root.af_shortcut_system.shortcuts if s.name == args.shortcut)
        self.initial = float(self.shortcut.proxy_float)
        self.plan = [(kind, i) for kind in args.scenarios.split(',') for i in range(args.repeats)]
        self.trace = RebuildTrace(); self.profiler = None; self.index = -1
        self.started = self.previous = time.perf_counter(); self.samples = []
        self.data = dict(args=vars(args), source=bpy.data.filepath, sha256=digest(bpy.data.filepath), code=source_identity(),
                         blender=bpy.app.version_string, background=bpy.app.background, objects=len(bpy.context.scene.objects),
                         muscles=muscle_inventory(self.root), episodes=[], initial_meshes=mesh_snapshot(), shortcut_initial=self.initial)
        self.record = None; experiment(args.experiment)
        runtime_trace.set_request_telemetry(True); runtime_trace.clear_request_telemetry()
        if args.instrument != 'none': self.trace.install()
        self.save()

    def action(self, kind, index):
        if kind == 'shortcut':
            self.shortcut.proxy_float = self.initial * (1.01 if index % 2 == 0 else 1.0)
        elif kind == 'full':
            ids = {m.id for m in self.root.af_vcp_system.muscles}
            with full_ablation(self.args.experiment):
                sync_runner.sync_from_dirty_hints(self.root, bpy.context.scene, {'MUSCLE': ids}, source='muscle_probe', event_type='UPDATE', full=False)
        elif kind == 'property':
            change_muscle(self.root, self.args.muscle, index)
        elif kind != 'idle': raise ValueError('Unknown scenario: ' + kind)

    def begin(self):
        kind, index = self.plan[self.index]; name = f'{self.index+1:02d}_{kind}_{index+1}'
        self.record = dict(name=name, scenario=kind, repeat=index, before=mesh_snapshot(),
                           shortcut_before=float(self.shortcut.proxy_float), warning_before=warning_state())
        self.trace.episode, self.trace.phase, self.trace.active = name, 'action', self.args.instrument != 'none'
        self.profiler = cProfile.Profile() if self.args.instrument == 'profile' else None
        runtime_trace.clear_request_telemetry()
        self.measure_action(kind, index)
        self.record.update(shortcut_after=float(self.shortcut.proxy_float), after_action=mesh_snapshot())
        self.flush()
        self.trace.phase = 'settle'; self.started = self.previous = time.perf_counter(); self.samples = []
        if self.profiler and self.args.profile_scope == 'settle': self.profiler.enable()
        print('MUSCLE_PROBE_ACTION', name, self.record['action_ms'], flush=True)

    def measure_action(self, kind, index):
        if self.profiler and self.args.profile_scope != 'settle': self.profiler.enable()
        started = time.perf_counter(); self.action(kind, index)
        self.record['action_ms'] = (time.perf_counter()-started)*1000
        if self.profiler and self.args.profile_scope == 'action': self.profiler.disable()

    def flush(self):
        self.trace.phase = 'flush'; previous = bpy.app.debug_depsgraph_time
        if self.args.depsgraph_timing:
            print('MUSCLE_PROBE_FLUSH_BEGIN', self.record['name'], flush=True)
            bpy.app.debug_depsgraph_time = True
        started = time.perf_counter()
        try: bpy.context.view_layer.update()
        finally:
            self.record['flush_ms'] = (time.perf_counter()-started)*1000
            bpy.app.debug_depsgraph_time = previous
        if self.args.depsgraph_timing: print('MUSCLE_PROBE_FLUSH_END', self.record['name'], flush=True)

    def end(self):
        if self.profiler:
            self.profiler.disable(); self.profiler.dump_stats(str(self.output/(self.record['name']+'.pstats')))
        self.trace.active = False
        self.record.update(after=mesh_snapshot(), telemetry=list(runtime_trace.request_telemetry()),
                           settle_samples=self.samples, final_pending=pending(), profile_cache=cache_state(), warning_after=warning_state())
        if self.profiler: write_json(self.output/(self.record['name']+'.functions.json'), profile_rows(self.profiler))
        self.data['episodes'].append(self.record); self.save()

    def save(self):
        write_json(self.output/'measurements.json', self.data)

    def finish(self):
        self.trace.close(); self.trace.export(self.output)
        self.data['source_unchanged'] = digest(self.data['source']) == self.data['sha256']
        self.data['finished'] = True; self.save()
        print('MUSCLE_PROBE_FINISHED', self.data['source_unchanged'], flush=True)
        bpy.ops.wm.quit_blender()

    def advance(self):
        now = time.perf_counter(); self.samples.append(dict(gap_ms=(now-self.previous)*1000, **pending())); self.previous = now
        duration = self.args.baseline if self.index < 0 else self.args.settle
        if now-self.started < duration: return .1
        if self.index >= 0: self.end()
        else: self.data['baseline_samples'] = self.samples
        self.index += 1
        if self.index == len(self.plan): self.finish(); return None
        self.begin(); return .1

    def tick(self):
        try: return self.advance()
        except BaseException:
            if self.profiler: self.profiler.disable()
            self.trace.close(); write_json(self.output/'error.json', dict(error=traceback.format_exc()))
            bpy.ops.wm.quit_blender(); return None


def main():
    if bpy.app.background: raise RuntimeError('Run without --background for real event-loop measurements.')
    probe = Probe(arguments())
    bpy.app.timers.register(probe.tick, first_interval=.1)


if __name__ == '__main__': main()
