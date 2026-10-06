"""Owned asynchronous C++ sessions, with summary-only normal publication."""
import ctypes as C
from dataclasses import asdict
import numpy as np
from . import abi
from .model import snapshot

STAT_KEYS = ('eligible_pairs', 'broad_pairs', 'detected_pairs', 'triangle_queries', 'projection_warnings',
             'broad_ms', 'narrow_ms', 'native_detection_ms', 'fragments', 'points', 'computed', 'reused',
             'preparation_ms', 'native_total_ms', 'assembly_ms', 'result_bytes')


def pair_record(row, index, domains):
    state = 'projection_requires_review' if row.warnings else 'geometric_candidate' if row.count else 'no_footprint'
    return dict(index=index, first=asdict(domains[row.first].key), second=asdict(domains[row.second].key),
                fragments=row.count, points=row.points, projection_warnings=row.warnings, status=state, activation_ready=False)


class NativePairEngine:
    def __init__(self):
        self.library = abi.library()
        self.handle = self.library.af_pair_create()
        if not self.handle: raise RuntimeError('PAIR_NATIVE_CREATE_FAILED')
        self.identities, self.domains, self.generation, self.rows = {}, {}, 0, None
        self.next_code = 0

    def code(self, kind, value):
        key = kind, value
        if key not in self.identities:
            self.next_code += 1; self.identities[key] = self.next_code
        return self.identities[key]

    def _input(self, domain):
        key = domain.key; p = abi.pointer
        return abi.Input(self.code('domain', key), p(domain.base), p(domain.own), p(domain.direction),
            p(domain.faces), p(domain.parts), p(domain.sources), len(domain.base), len(domain.faces),
            self.code('group', domain.group), self.code('root', key.root), self.code('instance', key.instance),
            int(domain.enabled), int(key.side == 'B'), domain.displacement)

    def submit(self, domains, settings, generation, exhaustive=False):
        if not self.handle: raise RuntimeError('PAIR_CLOSED')
        values = tuple(owned(v) for v in domains); inputs = (abi.Input * len(values))(*(self._input(v) for v in values))
        config = abi.Settings(settings.search_distance, settings.min_projected_area, settings.epsilon,
            settings.fragment_limit, settings.workers, settings.cache_bytes, settings.result_bytes)
        status = self.library.af_pair_submit(self.handle, inputs, len(values), C.byref(config), generation, int(exhaustive))
        if status: raise ValueError('PAIR_BUSY' if status == 2 else 'PAIR_SUBMISSION_INVALID')
        self.domains = {self.code('domain', v.key): v for v in values}
        self.generation, self.rows = generation, None
        live = live_identities(values)
        self.identities = {k: v for k, v in self.identities.items() if k in live}

    def poll(self):
        report = abi.Report()
        if not self.handle or self.library.af_pair_poll(self.handle, C.byref(report)): raise RuntimeError('PAIR_NO_JOB')
        return report

    def summary(self):
        report = self.poll()
        if report.state != 2: raise RuntimeError(report.message.decode() or 'PAIR_NOT_READY')
        self.rows = (abi.Pair * int(report.stats[1]))()
        if self.library.af_pair_summary(self.handle, self.generation, self.rows, len(self.rows)): raise RuntimeError('PAIR_STALE_RESULT')
        return dict(pairs=tuple(pair_record(row, i, self.domains) for i, row in enumerate(self.rows)),
                    timings=dict(zip(STAT_KEYS, report.stats), **storage_stats(self)), generation=self.generation)

    def footprint(self, index, generation):
        if generation != self.generation or self.rows is None: raise ValueError('PAIR_STALE_RESULT')
        if not 0 <= index < len(self.rows): raise ValueError('PAIR_NOT_FOUND')
        row = self.rows[index]; fragments, points = (abi.Fragment * row.count)(), (abi.Point * row.points)()
        status = self.library.af_pair_footprint(self.handle, generation, index, fragments, len(fragments), points, len(points))
        if status: raise ValueError('PAIR_FOOTPRINT_RESOURCE_LIMIT' if status == 3 else 'PAIR_STALE_RESULT')
        return dict(fragment_array=np.ctypeslib.as_array(fragments), point_array=np.ctypeslib.as_array(points))

    def cancel(self):
        if self.handle and self.generation: self.library.af_pair_cancel(self.handle, self.generation)

    def release(self):
        if self.handle and self.library.af_pair_release(self.handle, self.generation): raise RuntimeError('PAIR_BUSY')

    def close(self):
        if self.handle: self.library.af_pair_destroy(self.handle)
        self.handle, self.domains, self.rows = None, {}, None

    def __enter__(self): return self

    def __exit__(self, *_): self.close()


def owned(value):
    return snapshot(value.key, value.group, value.revision, value.base, value.own, value.direction,
        value.faces, value.parts, value.sources, value.displacement, value.enabled)


def live_identities(values):
    return {entry for v in values for entry in (('domain', v.key), ('group', v.group),
                                               ('root', v.key.root), ('instance', v.key.instance))}


def storage_stats(engine):
    values = (C.c_double * 4)()
    if engine.library.af_pair_storage_stats(engine.handle, engine.generation, values, 4): raise RuntimeError('PAIR_STALE_RESULT')
    return dict(zip(('detection_peak_working_bytes', 'pair_summary_cache_bytes', 'footprint_logical_bytes'), values))
