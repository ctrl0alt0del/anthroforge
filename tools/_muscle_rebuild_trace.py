"""Opt-in buffered span logging for the muscle rebuild probe; no scene writes."""
from collections import defaultdict
from functools import wraps
import importlib
import inspect
import json
from pathlib import Path
import re
import sys
import time

PREFIX = 'anthroforge.'
MODULES = (
    'core.visualization.muscle_sync', 'core.visualization.muscle_numeric_runtime',
    'core.visualization.muscle_sync_helpers', 'core.visualization.muscle_sync_runtime',
    'core.visualization.muscle_profile_capture', 'core.visualization.muscle_envelope_storage',
    'core.visualization.muscle_envelope_overlay', 'core.visualization.branched_surface_capture',
    'core.vcp.muscle_numeric', 'core.vcp.muscle_numeric_native', 'core.vcp.free_muscle_numeric',
    'core.vcp.muscle_profile_numeric', 'core.vcp.muscle_profile_cache', 'core.vcp.muscle_profile_frames',
    'core.vcp.muscle_output_domain', 'core.vcp.muscle_domain_clip', 'core.vcp.muscle_envelope',
    'core.vcp.muscle_envelope_native', 'core.vcp.prepared_inflation', 'core.vcp.prepared_inflation_native',
    'core.vcp.branched_numeric', 'core.vcp.branched_surface', 'core.vcp.branch_connector',
    'core.vcp.free_surface', 'core.vcp.free_surface_stations',
    'core.vcp.prepared_cache', 'core.vcp.surface_preparation_cache',
)
EXTRA = {
    'core.visualization.fiber_surface_sync': ('evaluate_surface_record', 'FiberSurfaceSceneSync.sync_root_to_scene'),
    'core.visualization.vcp_mirror_runtime': ('sync_vcp_mirrors',),
    'core.visualization.sync_runner': ('_run_one_request',),
    'core.scp_runtime.sync_runtime': ('sync_root_to_scene',),
    'core.utils': ('depsgraph_for_scene', 'update_scene_view_layer'),
    'core.deps.runtime_context_build': ('_graph_stamp', '_graph_data'),
    'core.visualization.warning_capture': ('capture_pin', 'capture_root', 'owner_in_scope'),
    'core.visualization.warning_pipeline': ('fiber_result', 'publish_current'),
    'core.warnings.native_executor': ('NativeWarningExecutor.submit', 'NativeWarningExecutor.read'),
    'core.warnings.coordinator': ('Coordinator.tick',),
    'ui.warnings': ('refresh', '_project_rows'),
}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def function_targets(module):
    for value in tuple(vars(module).values()):
        if inspect.isfunction(value) and value.__module__ == module.__name__: yield value
        if inspect.isclass(value) and value.__module__ == module.__name__:
            for method in vars(value).values():
                if inspect.isfunction(method) and not method.__name__.startswith('__'): yield method


def selected_targets():
    targets = set()
    for name in MODULES: targets.update(function_targets(importlib.import_module(PREFIX + name)))
    for name, paths in EXTRA.items():
        module = importlib.import_module(PREFIX + name)
        for path in paths:
            owner = module
            for part in path.split('.'): owner = getattr(owner, part)
            targets.add(owner)
    return targets


def identity(value):
    if isinstance(value, str): return value if value.startswith('MUSCLE_') else ''
    if value is None: return ''
    if hasattr(value, 'muscle'): return str(value.muscle.id)
    if hasattr(value, 'muscle_id'): return str(value.muscle_id)
    if hasattr(value, 'id') and str(value.id).startswith('MUSCLE_'): return str(value.id)
    if hasattr(value, 'get'): return str(value.get('af_muscle_id', '') or '')
    return ''


def call_metadata(names, args, kwargs):
    values = dict(zip(names, args)); values.update(kwargs)
    keys = ('muscle', 'muscle_id', 'work', 'request', 'obj')
    muscle = next((found for key in keys if (found := identity(values.get(key)))), '')
    info = {'muscle': muscle} if muscle else {}
    if 'obj' in values and hasattr(values['obj'], 'type'):
        obj = values['obj']; info.update(object=obj.name, role=obj.get('af_muscle_surface', ''))
    if 'key' in values and 'factory' in values:
        from anthroforge.core.vcp.muscle_profile_cache import CACHE
        info['cache_hit'] = values['key'] in CACHE
    return info


def result_metadata(result):
    info = {}
    if hasattr(result, 'base_vertices'):
        info.update(vertices=len(result.base_vertices), faces=len(result.faces), error=getattr(result, 'error', ''))
    if hasattr(result, 'request') and hasattr(result, 'stale'):
        info.update(stale=result.stale, error=result.error, has_request=result.request is not None)
    if hasattr(result, 'backend') and hasattr(result, 'elapsed_ms') and hasattr(result, 'results'):
        info.update(backend=result.backend, reported_ms=result.elapsed_ms, muscles=len(result.results),
                    workers=result.workers, parallel=result.parallel)
    return info


def safe_metadata(callback, *args):
    try: return callback(*args)
    except Exception as error: return {'logging_error': type(error).__name__ + ': ' + str(error)}


class NativeCall:
    def __init__(self, original, invoke):
        object.__setattr__(self, 'original', original)
        object.__setattr__(self, 'invoke', invoke)

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __setattr__(self, name, value):
        setattr(self.original, name, value)

    def __call__(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)


class RebuildTrace:
    def __init__(self):
        self.rows, self.stack, self.restores = [], [], []
        self.active, self.episode, self.phase = False, '', ''
        self.origin = time.perf_counter_ns()

    def wrap(self, original, label=None, native=False):
        label = label or original.__module__.removeprefix(PREFIX) + '.' + original.__qualname__
        names = () if native else tuple(inspect.signature(original).parameters)
        @wraps(original)
        def measured(*args, **kwargs):
            if not self.active: return original(*args, **kwargs)
            row = self.enter(label, names, args, kwargs)
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                self.leave(row, error=type(error).__name__); raise
            self.leave(row, result=result)
            return result
        return measured

    def enter(self, label, names, args, kwargs):
        info = safe_metadata(call_metadata, names, args, kwargs)
        parent = self.stack[-1] if self.stack else None
        row = dict(id=len(self.rows), parent=parent['id'] if parent else None, name=label,
                   episode=self.episode, phase=self.phase, children_ns=0, **info)
        if parent and not row.get('muscle'): row['muscle'] = parent.get('muscle', '')
        self.rows.append(row); self.stack.append(row)
        row['start_ns'] = time.perf_counter_ns()
        return row

    def leave(self, row, result=None, error=''):
        end = time.perf_counter_ns(); elapsed = end - row.pop('start_ns')
        row['start_us'] = (end - elapsed - self.origin) / 1000
        row['ms'], row['self_ms'] = elapsed / 1e6, (elapsed-row.pop('children_ns')) / 1e6
        self.stack.pop()
        if self.stack: self.stack[-1]['children_ns'] += elapsed
        row.update(safe_metadata(result_metadata, result))
        if error: row['exception'] = error

    def replace(self, owner, name, value):
        self.restores.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def install(self):
        replacements = {fn: self.wrap(fn) for fn in selected_targets()}
        for module in tuple(sys.modules.values()):
            if not getattr(module, '__name__', '').startswith(PREFIX): continue
            self.patch_owner(module, replacements)
            for value in tuple(vars(module).values()):
                if inspect.isclass(value) and value.__module__ == module.__name__:
                    self.patch_owner(value, replacements)
        self.install_native()

    def patch_owner(self, owner, replacements):
        for name, value in tuple(vars(owner).items()):
            if inspect.isfunction(value) and value in replacements:
                self.replace(owner, name, replacements[value])

    def install_native(self):
        from anthroforge.core.vcp.v2.collision_native import load_native
        library = load_native(); names = {'af_warning_async_submit', 'af_warning_async_read'}
        folder = Path(__file__).resolve().parents[1] / 'core' / 'vcp'
        for path in folder.glob('*.py'):
            names.update(re.findall(r'\baf_(?:muscle|prepared|profile|branch)[A-Za-z0-9_]*', path.read_text(encoding='utf-8-sig')))
        for name in sorted(names):
            try: original = getattr(library, name)
            except AttributeError: continue
            invoke = self.wrap(original, 'native.' + name, native=True)
            self.replace(library, name, NativeCall(original, invoke))

    def close(self):
        self.active = False
        for owner, name, original in reversed(self.restores): setattr(owner, name, original)
        self.restores.clear()

    def export(self, folder):
        Path(folder, 'spans.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in self.rows), encoding='utf-8')
        events = [dict(name=r['name'], cat=r['phase'], ph='X', ts=r['start_us'], dur=r['ms']*1000,
                       pid=1, tid=r['episode'], args={k:v for k,v in r.items() if k not in {'name','start_us','ms'}}) for r in self.rows]
        write_json(Path(folder, 'trace.json'), dict(traceEvents=events, displayTimeUnit='ms'))
        write_json(Path(folder, 'stages.json'), self.aggregate())

    def aggregate(self):
        groups = defaultdict(list)
        for row in self.rows: groups[(row['episode'], row['phase'], row['name'], row.get('muscle', ''))].append(row)
        return [dict(episode=k[0], phase=k[1], name=k[2], muscle=k[3], calls=len(rows),
                     total_ms=sum(r['ms'] for r in rows), self_ms=sum(r['self_ms'] for r in rows),
                     max_ms=max(r['ms'] for r in rows), cache_hits=sum(r.get('cache_hit', False) for r in rows))
                for k, rows in groups.items()]
