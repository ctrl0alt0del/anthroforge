"""Measure a shortcut and subsequent real Blender event-loop activity.

Launch Blender with the input blend, --python this_script, then -- --output DIR.
The probe edits only the in-memory scene, verifies the source hash, and quits.
Use --profile for call attribution; profiler overhead changes absolute timings.
Experimental switches isolate causes and are not production fixes. The optional
geometry guard compares evaluated positions, topology, and world matrices only.
The 100 ms heartbeat measures main-thread availability, not viewport frame rate.
"""

import argparse
from collections import Counter, defaultdict
import cProfile
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

import bpy
import numpy as np

from anthroforge.core.deps import runtime_trace
from anthroforge.core.utils import get_af_root
from anthroforge.core.visualization import fiber_refinement, sync_runner, warning_runtime
from anthroforge.core.warnings import session
from anthroforge.core.scp_runtime import sync_runtime as scp_runtime, attachment_wave_runtime


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--shortcut', default='Pubis Arc Radius')
    parser.add_argument('--baseline', type=float, default=20)
    parser.add_argument('--after', type=float, default=60)
    parser.add_argument('--factor', type=float, default=1.01)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--disable-warnings', action='store_true')
    experiment_arguments(parser)
    parser.add_argument('--mute-scp-after', type=float, default=0)
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def experiment_arguments(parser):
    parser.add_argument('--no-edit', action='store_true')
    parser.add_argument('--skip-scp-mirrors', action='store_true')
    parser.add_argument('--skip-role-sync', action='store_true')
    parser.add_argument('--guard-after', type=float, default=0)
    parser.add_argument('--verify-edit', action='store_true')


def write(path, data):
    path.write_text(json.dumps(data, indent=2, default=str), encoding='utf-8')


def fingerprint():
    return hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()


def pending():
    return dict(runtime=len(sync_runner._PENDING), tail=len(sync_runner._TAIL_PENDING),
                fibers=len(fiber_refinement._JOBS), warnings=len(warning_runtime._TARGETS),
                warning_timer=bpy.app.timers.is_registered(warning_runtime.tick))


def inventory(root):
    fibers = root.af_vcp_system.fibers
    return dict(file=bpy.data.filepath, blender=bpy.app.version_string, background=bpy.app.background,
                objects=len(bpy.context.scene.objects), scps=len(root.af_scp_system.scps),
                fibers=len(fibers), muscles=len(root.af_vcp_system.muscles),
                fiber_modes=dict(Counter(str(getattr(f, 'behavior_mode', 'unknown')) for f in fibers)),
                addons=list(bpy.context.preferences.addons.keys()), gn_dependencies=gn_dependencies(), drivers=driver_inventory(),
                geometry=[(s.id, s.geometry_object_ref.name if s.geometry_object_ref else '',
                [(m.name, m.node_group.name) for m in s.geometry_object_ref.modifiers if m.type == 'NODES' and m.node_group]) for s in root.af_scp_system.scps if s.geometry_object_ref])


def gn_dependencies():
    rows = []
    kinds = {'GeometryNodeObjectInfo', 'GeometryNodeCollectionInfo', 'GeometryNodeInputSceneTime', 'GeometryNodeSelfObject'}
    for group in bpy.data.node_groups:
        for node in group.nodes:
            if node.bl_idname not in kinds: continue
            inputs = {s.name: getattr(s.default_value, 'name', str(s.default_value)) for s in node.inputs if hasattr(s, 'default_value')}
            rows.append(dict(group=group.name, node=node.name, kind=node.bl_idname, inputs=inputs))
    return rows


def driver_inventory():
    rows = []
    for obj in bpy.data.objects:
        animation = obj.animation_data
        for curve in (() if animation is None else animation.drivers):
            targets = [(v.name, getattr(t.id, 'name', None), t.data_path) for v in curve.driver.variables for t in v.targets]
            rows.append(dict(object=obj.name, path=curve.data_path, expression=curve.driver.expression, targets=targets))
    return rows


class Probe:
    def __init__(self, args):
        self.args = args; self.output = Path(args.output); self.output.mkdir(parents=True, exist_ok=True)
        self.root = get_af_root(bpy.context.scene); self.row = next(s for s in self.root.af_shortcut_system.shortcuts if s.name == args.shortcut)
        self.data = dict(inventory=inventory(self.root), source_sha256=fingerprint(), shortcut=args.shortcut, args=vars(args), phases=[])
        self.samples = []; self.events = []; self.calls = defaultdict(list); self.restores = []
        self.phase = 'baseline'; self.started = self.previous = time.perf_counter(); self.last_save = 0
        self.profiler = cProfile.Profile() if args.profile else None
        runtime_trace.set_request_telemetry(True); runtime_trace.clear_request_telemetry()
        if args.disable_warnings: warning_runtime.unregister()
        self.install(); self.begin(); self.save()

    def timed(self, callback, name):
        def measured(*args, **kwargs):
            started = time.perf_counter()
            if name == '_run_one_request': self.request_event(args[1])
            try: return callback(*args, **kwargs)
            finally:
                elapsed = 1000 * (time.perf_counter() - started)
                self.calls[name].append(elapsed)
                if elapsed > 10: self.events.append(dict(phase=self.phase, name=name, ms=elapsed, at=started-self.started))
        return measured

    def wrap(self, owner, name):
        original = getattr(owner, name); self.restores.append((owner, name, original))
        setattr(owner, name, self.timed(original, name))

    def install(self):
        self.experiments()
        self.wrap(sync_runner, '_run_one_request')
        self.wrap(session.COORDINATOR, 'tick')
        self.filter_original = scp_runtime._depsgraph_change_sets
        self.restores.append((scp_runtime, '_depsgraph_change_sets', self.filter_original))
        scp_runtime._depsgraph_change_sets = self.filtered_changes
        handlers = bpy.app.handlers.depsgraph_update_post
        self.original_handlers = tuple(handlers)
        for index, callback in enumerate(tuple(handlers)):
            handlers[index] = self.timed(callback, callback.__module__ + '.' + callback.__qualname__)

    def experiments(self):
        for enabled, name in ((self.args.skip_scp_mirrors, 'sync_mirrors'), (self.args.skip_role_sync, '_sync_roles')):
            if not enabled: continue
            self.restores.append((scp_runtime, name, getattr(scp_runtime, name)))
            setattr(scp_runtime, name, lambda *args, **kwargs: None)
        if self.args.guard_after: self.install_geometry_audit()

    def install_geometry_audit(self):
        self.geometry_cache = {}; self.guard_geometry = False
        self.collect_original = scp_runtime._collect_update
        self.restores.append((scp_runtime, '_collect_update', self.collect_original))
        for scp in self.root.af_scp_system.scps:
            if scp.geometry_object_ref: self.geometry_cache[scp.id] = geometry_arrays(scp.geometry_object_ref)
        scp_runtime._collect_update = self.collect_update

    def collect_update(self, root, depsgraph, update, changed, transformed, geometry):
        obj = update.id
        if not isinstance(obj, bpy.types.Object) or not scp_runtime.is_bound_scp_obj(obj, root.name):
            return self.collect_original(root, depsgraph, update, changed, transformed, geometry)
        if not obj.get('af_scp_geometry') or not (update.is_updated_geometry or update.is_updated_transform):
            return self.collect_original(root, depsgraph, update, changed, transformed, geometry)
        sid = str(obj.get('af_scp_id')); arrays = geometry_arrays(obj.original)
        delta = geometry_delta(self.geometry_cache.get(sid), arrays); self.geometry_cache[sid] = arrays
        self.events.append(dict(name='geometry_audit', scp=sid, object=obj.name, **delta))
        if self.guard_geometry and delta['same']: return
        return self.collect_original(root, depsgraph, update, changed, transformed, geometry)

    def request_event(self, request):
        self.events.append(dict(name='request_start', at=time.perf_counter()-self.started,
                               source=request.source, event=request.event_type,
                               dirty={key: sorted(value) for key, value in (request.dirty_hints or {}).items()}, payload=request.payload))

    def filtered_changes(self, root, depsgraph):
        result = self.filter_original(root, depsgraph)
        changed, transformed, geometry = result
        if changed:
            self.events.append(dict(name='scp_changes', at=time.perf_counter()-self.started,
                raw=sorted(changed), transformed=sorted(transformed), geometry=sorted(geometry), kept=sorted(result[0])))
        return result

    def begin(self):
        self.phase_started = self.previous = time.perf_counter()
        self.samples = []; self.events = []; self.calls = defaultdict(list)
        self.cpu_start = time.process_time()
        if self.profiler: self.profiler.enable()
        print('PERF_PHASE', self.phase, pending(), flush=True)

    def sample(self):
        now = time.perf_counter()
        self.samples.append(dict(at=now-self.phase_started, gap_ms=1000*(now-self.previous), **pending()))
        self.previous = now
        if now-self.last_save > 2: self.save(); self.last_save = now

    def phase_result(self):
        return dict(name=self.phase, seconds=time.perf_counter()-self.phase_started,
                    cpu_seconds=time.process_time()-self.cpu_start, samples=self.samples, events=self.events,
                    calls={key: dict(count=len(values), total_ms=sum(values), max_ms=max(values)) for key, values in self.calls.items()},
                    telemetry=list(runtime_trace.request_telemetry()), warning_metrics=dict(session.COORDINATOR.metrics),
                    attachment_report=asdict(attachment_wave_runtime.last_attachment_wave_report(self.root)))

    def end(self):
        if self.profiler:
            self.profiler.disable(); self.profiler.dump_stats(str(self.output/(self.phase+'.pstats'))); self.profiler.clear()
        self.data['phases'].append(self.phase_result())
        runtime_trace.clear_request_telemetry(); self.save()

    def save(self):
        write(self.output/'measurements.json', dict(self.data, current=self.phase_result()))

    def edit(self):
        self.phase = 'shortcut'; self.begin()
        before = float(self.row.proxy_float); started = time.perf_counter()
        if not self.args.no_edit: self.row.proxy_float = before*self.args.factor
        self.data['edit'] = dict(before=before, after=float(self.row.proxy_float), ms=1000*(time.perf_counter()-started))
        self.data.setdefault('edits', []).append(dict(self.data['edit']))
        self.end(); self.phase = 'after'; self.begin()

    def finish(self):
        self.data['source_unchanged'] = fingerprint() == self.data['source_sha256']; self.save()
        bpy.app.handlers.depsgraph_update_post[:] = self.original_handlers
        for owner, name, original in self.restores: setattr(owner, name, original)
        print('PERF_FINISHED', self.data['edit'], pending(), flush=True)
        bpy.ops.wm.quit_blender()

    def advance(self):
        self.sample(); duration = self.args.baseline if self.phase == 'baseline' else self.args.after
        if self.phase in {'muted', 'guarded'}: duration = self.args.mute_scp_after or self.args.guard_after
        if time.perf_counter()-self.phase_started < duration: return .1
        self.end()
        if self.phase == 'baseline': self.edit(); return .1
        if self.phase == 'after' and (self.args.mute_scp_after or self.args.guard_after): self.mute(); return .1
        if self.args.verify_edit and not self.data.get('second_edit'):
            self.data['second_edit'] = True; self.edit(); return .1
        self.finish(); return None

    def mute(self):
        if self.args.guard_after:
            self.guard_geometry = True; self.phase = 'guarded'; self.begin(); return
        self.restores.append((scp_runtime, '_sync_from_depsgraph', scp_runtime._sync_from_depsgraph))
        scp_runtime._sync_from_depsgraph = lambda *args: None
        self.phase = 'muted'; self.begin()

    def tick(self):
        try: return self.advance()
        except Exception:
            write(self.output/'error.json', dict(error=traceback.format_exc()))
            if self.profiler: self.profiler.disable()
            bpy.ops.wm.quit_blender(); return None


def geometry_arrays(obj):
    evaluated = obj.evaluated_get(bpy.context.view_layer.depsgraph); mesh = evaluated.to_mesh()
    try:
        positions = np.empty(len(mesh.vertices)*3, dtype=np.float32); mesh.vertices.foreach_get('co', positions)
        loops = np.empty(len(mesh.loops), dtype=np.int32); mesh.loops.foreach_get('vertex_index', loops)
        faces = np.empty(len(mesh.polygons), dtype=np.int32); mesh.polygons.foreach_get('loop_total', faces)
        return np.asarray(evaluated.matrix_world, dtype=np.float32), positions, loops, faces
    finally: evaluated.to_mesh_clear()


def geometry_delta(before, after):
    compatible = before is not None and all(a.shape == b.shape for a, b in zip(before, after))
    same = compatible and all(np.array_equal(a, b) for a, b in zip(before, after))
    return dict(same=same, matrix_delta=None if not compatible else float(np.max(np.abs(before[0]-after[0]))),
                vertex_delta=None if not compatible else float(np.max(np.abs(before[1]-after[1]), initial=0)))


def main():
    if bpy.app.background: raise RuntimeError('Run without --background to measure the actual event loop.')
    probe = Probe(arguments())
    bpy.app.timers.register(probe.tick, first_interval=.1)


if __name__ == '__main__': main()
