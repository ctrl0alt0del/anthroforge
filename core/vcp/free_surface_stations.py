"""Opt-in material correspondence for authored Free lofts; identity guarded."""
import json
import numpy as np
from .free_path import decode, is_free
from .free_surface import prepare_rows, check_budget

KEY = 'af_authoring_free_surface_stations'


def resolve(surface, fibers, payloads=None):
    raw = surface.get(KEY, '') if hasattr(surface, 'get') else ''
    if not raw: return ()
    value = json.loads(raw)
    if value.get('version') != 1 or [r['fiber_id'] for r in value['rows']] != [f.id for f in fibers]:
        raise ValueError('FREE_CORRESPONDENCE_STALE: source fiber order changed; rebuild the authored correspondence.')
    rows = []
    for row, fiber in zip(value['rows'], fibers):
        if not is_free(fiber): raise ValueError('FREE_CORRESPONDENCE_MODE: requires Free fibers.')
        payload = (payloads or {}).get(fiber.id) or decode(fiber.free_path_json)
        rows.append(remap(row, payload))
    return tuple(rows)


def remap(row, payload):
    ids = [s['sample_id'] for s in payload['samples']]
    if ids == row['sample_ids']: return row['stations']
    if 'reference_points' not in row: raise ValueError('FREE_CORRESPONDENCE_STALE: rebuild the authored correspondence.')
    lookup = {key: i for i, key in enumerate(row['sample_ids'])}
    anchors = [(lookup[key], i) for i, key in enumerate(ids) if key in lookup]
    if not anchors or anchors[0] != (0, 0) or anchors[-1] != (len(lookup)-1, len(ids)-1) or any(a[0] >= b[0] for a, b in zip(anchors, anchors[1:])):
        raise ValueError('FREE_CORRESPONDENCE_STALE: endpoint identity or longitudinal order changed.')
    old = np.asarray(row['reference_points']); new = np.asarray([s['co'] for s in payload['samples']]); result = np.empty(len(ids))
    for (a, c), (b, d) in zip(anchors, anchors[1:]):
        result[c:d+1] = np.interp(fractions(new[c:d+1]), fractions(old[a:b+1]), row['stations'][a:b+1])
    return result.tolist()


def fractions(points):
    values = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if values[-1] <= 1e-12: raise ValueError('FREE_CORRESPONDENCE_DEGENERATE')
    return values/values[-1]


def prepare(rows, stations, multiplier=4):
    from .fiber_surface import _densify_rows, _average_row_step, _row_inserts
    if len(rows) != len(stations): raise ValueError('FREE_CORRESPONDENCE_ROWS')
    values = [np.asarray(s, float) for s in stations]
    for row, s in zip(rows, values):
        if s.shape != (len(row),) or not np.isfinite(s).all() or np.any(np.diff(s) <= 0): raise ValueError('FREE_CORRESPONDENCE_STATIONS')
    if any(abs(s[0]-values[0][0])+abs(s[-1]-values[0][-1]) > 1e-10 for s in values): raise ValueError('FREE_CORRESPONDENCE_EXTENTS')
    target = np.unique(np.concatenate(values)); check_budget(len(rows)*len(target), 2*(len(rows)-1)*len(target), multiplier)
    output = [np.column_stack([np.interp(target, s, np.asarray(row)[:, axis]) for axis in range(3)]).tolist() for row, s in zip(rows, values)]
    step = _average_row_step(output); inserts = sum(_row_inserts(a, b, step, 0) for a, b in zip(output, output[1:]))
    check_budget((len(rows)+inserts)*len(target), 2*(len(rows)+inserts-1)*len(target), multiplier)
    return _densify_rows(output, 0)


def prepare_record(source, fibers, rows, closed=False):
    stations = resolve(source, fibers)
    if not stations: return prepare_rows(rows, closed, multiplier=4)
    if closed: raise ValueError('FREE_CORRESPONDENCE_CLOSED: authored stations require an open loft.')
    return prepare(rows, stations)
