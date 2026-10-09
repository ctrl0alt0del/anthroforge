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


def prepare(rows, stations, multiplier=4, across_inserts=()):
    from .surface_preparation_cache import prepared_rows
    from .muscle_profile_cache import content_key
    keys = tuple(content_key(np.asarray(row, dtype=float)) for row in stations)
    return prepared_rows('stations', rows, (keys, multiplier, across_inserts), lambda: _prepare(rows, stations, multiplier, across_inserts))


def _prepare(rows, stations, multiplier, across_inserts=()):
    from .fiber_surface import _densify_rows, _average_row_step, _row_inserts
    if len(rows) != len(stations): raise ValueError('FREE_CORRESPONDENCE_ROWS')
    values = [np.asarray(s, float) for s in stations]
    for row, s in zip(rows, values):
        if s.shape != (len(row),) or not np.isfinite(s).all() or np.any(np.diff(s) <= 0): raise ValueError('FREE_CORRESPONDENCE_STATIONS')
    if any(abs(s[0]-values[0][0])+abs(s[-1]-values[0][-1]) > 1e-10 for s in values): raise ValueError('FREE_CORRESPONDENCE_EXTENTS')
    target = station_union(values); check_budget(len(rows)*len(target), 2*(len(rows)-1)*len(target), multiplier)
    output = [np.column_stack([np.interp(target, s, np.asarray(row)[:, axis]) for axis in range(3)]).tolist() for row, s in zip(rows, values)]
    minimum = 1 if len(output) == 2 else 0
    step = _average_row_step(output)
    counts = across_inserts or tuple(_row_inserts(a, b, step, minimum) for a, b in zip(output, output[1:]))
    inserts = sum(counts)
    check_budget((len(rows)+inserts)*len(target), 2*(len(rows)+inserts-1)*len(target), multiplier)
    return _fixed_densify(output, counts)


def _fixed_densify(rows, counts):
    from .fiber_surface import _lerp
    if len(counts) != len(rows)-1: raise ValueError('FREE_CORRESPONDENCE_ACROSS')
    output = [rows[0]]
    for a,b,count in zip(rows,rows[1:],counts):
        output.extend([[_lerp(p,q,i/(count+1)) for p,q in zip(a,b)] for i in range(1,count+1)])
        output.append(b)
    return output


def material_layout(source, fibers):
    if getattr(source, 'use_mirrored_rows', False): fibers = _source_fibers(source, fibers)
    if not fibers or any(not is_free(f) or f.topology_mode != 'OPEN' for f in fibers): return resolve(source, fibers), ()
    reference = [[s['co'] for s in decode(f.free_path_json)['samples']] for f in fibers]
    stations = resolve(source, fibers) or tuple(fractions(np.asarray(row)).tolist() for row in reference)
    reference, stations = _mirror_layout(source, fibers, reference, stations)
    from .fiber_surface import _average_row_step, _row_inserts
    target = station_union(stations)
    sampled = [np.column_stack([np.interp(target,s,np.asarray(row)[:,axis]) for axis in range(3)]) for row,s in zip(reference,stations)]
    step = _average_row_step(sampled); minimum = int(len(sampled)==2)
    return stations, tuple(_row_inserts(a,b,step,minimum) for a,b in zip(sampled,sampled[1:]))


def _source_fibers(source, fibers):
    lookup = {f.id: f for f in fibers}
    return [lookup[r.fiber_id] for r in source.fiber_refs]


def _mirror_layout(source, fibers, rows, stations):
    if not getattr(source, 'use_mirrored_rows', False): return rows, stations
    from ..visualization.muscle_sync_runtime import _mirror_rule, _rows_span_plane, _row_signed_distance, _mirror_row
    from mathutils import Vector
    root = fibers[0].id_data; rule = _mirror_rule(root, source)
    rows = [[tuple(root.matrix_world @ Vector(p)) for p in row] for row in rows]
    if rule is None or _rows_span_plane(rows, *rule): return rows, stations
    ordered = sorted(zip(rows, stations), key=lambda item: abs(_row_signed_distance(item[0], *rule)))
    mirrors = [(_mirror_row(row, *rule), s) for row,s in ordered if abs(_row_signed_distance(row, *rule)) > 1e-6]
    combined = list(reversed(mirrors)) + ordered
    return [row for row,_s in combined], tuple(s for _row,s in combined)


def station_union(values):
    # Blender stores mesh and curve coordinates as float32: near-equal material
    # stations otherwise make zero-area slivers after publication to the mesh.
    ordered = np.sort(np.concatenate(values)); result = [float(ordered[0])]
    for value in ordered[1:]:
        if value-result[-1] > 8*np.finfo(np.float32).eps: result.append(float(value))
    result[-1] = float(ordered[-1])
    from .free_surface import MAX_STATIONS
    if len(result) > MAX_STATIONS: raise ValueError('FREE_STATION_BUDGET')
    return np.asarray(result)


def prepare_record(source, fibers, rows, closed=False):
    stations, counts = material_layout(source, fibers)
    if not stations: return prepare_rows(rows, closed, multiplier=4)
    if closed: raise ValueError('FREE_CORRESPONDENCE_CLOSED: authored stations require an open loft.')
    return prepare(rows, stations, across_inserts=counts)
