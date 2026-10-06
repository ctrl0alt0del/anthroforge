"""Preserve authored longitudinal material coordinates during native import."""
import json
import numpy as np
from ..vcp.free_surface_stations import KEY, remap
from ..vcp.free_path import decode


def checked(surface, fibers):
    if not surface.material_stations: return None
    value = json.loads(surface.material_stations); rows = value.get('rows', ())
    if value.get('version') != 1 or [r['fiber_id'] for r in rows] != surface.fiber_ids:
        raise ValueError('FREE_IMPORT_CORRESPONDENCE_IDENTITY')
    for row in rows:
        validate_row(row)
        payload = decode(fibers[row['fiber_id']].props.get('free_path_json', ''))
        if len(remap(row, payload)) != len(payload['samples']): raise ValueError('FREE_IMPORT_CORRESPONDENCE_SAMPLES')
    return value


def validate_row(row):
    values = np.asarray(row['stations'], dtype=float); ids = row['sample_ids']
    if values.shape != (len(ids),) or len(ids) < 2 or len(set(ids)) != len(ids):
        raise ValueError('FREE_IMPORT_CORRESPONDENCE_SAMPLES')
    if not np.isfinite(values).all() or np.any(np.diff(values) <= 0):
        raise ValueError('FREE_IMPORT_CORRESPONDENCE_STATIONS')
    if 'reference_points' in row:
        points = np.asarray(row['reference_points'], dtype=float)
        if points.shape != (len(ids), 3) or not np.isfinite(points).all():
            raise ValueError('FREE_IMPORT_CORRESPONDENCE_REFERENCE')


def validate(snapshot):
    fibers = {f.source_id: f for f in snapshot.fibers}
    for surface in getattr(snapshot, 'fiber_surfaces', ()): checked(surface, fibers)


def restore_surface(surface, destination, state):
    if not surface.material_stations: return
    value = json.loads(surface.material_stations)
    sources = {f.source_id: f for f in state.snapshot.fibers}
    targets = {f.id: f for f in state.root.af_vcp_system.fibers}
    for row in value['rows']:
        source = decode(sources[row['fiber_id']].props['free_path_json'])
        target = decode(targets[state.fibers[row['fiber_id']]].free_path_json)
        row.update(stations=remap(row, source), fiber_id=state.fibers[row['fiber_id']],
            sample_ids=[s['sample_id'] for s in target['samples']], reference_points=[s['co'] for s in target['samples']])
    destination[KEY] = json.dumps(value, separators=(',', ':'))


def restore(state):
    destinations = {s.id: s for s in state.root.af_vcp_system.fiber_surfaces}
    for surface in state.snapshot.fiber_surfaces:
        if surface.source_id in state.fiber_surfaces:
            restore_surface(surface, destinations[state.fiber_surfaces[surface.source_id]], state)
