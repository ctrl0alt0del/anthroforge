"""Resolve versioned indexed selections and immutable guide/protection snapshots."""
import numpy as np
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from . import transfer_bands


def indices(selection, row):
    if 'vertex_indices' in selection:
        return list(selection['vertex_indices'])
    faces = row['geometry']['triangles']; ids = selection['triangle_indices']
    require(all(0 <= i < len(faces) for i in ids), 'TRANSFER_SHAPE_INDEX')
    return sorted({int(v) for i in ids for v in faces[int(i)]})


def domain(rows, names, record):
    selection = record['selection']; name = selection['source_object']
    require(name in names, 'TRANSFER_SHAPE_BAND_SOURCE')
    band = dict(selection, vertex_indices=indices(selection, rows[name]))
    ids, _points = transfer_bands.source_indices(rows, names, band)
    return dict(record, source_object=name, vertex_indices=ids.tolist())


def coverage(rows, row):
    if 'coverage' not in row:
        return row
    source = rows[row['source_object']]; spec = row['coverage']; ids = indices(spec['intended'], source)
    require(ids and all(0 <= i < len(source['geometry']['vertices']) for i in ids), 'TRANSFER_SHAPE_INDEX')
    require(set(row['vertex_indices']) <= set(ids), 'TRANSFER_CONSTRAINT_OUTSIDE_INTENDED')
    axes = np.asarray(spec['axes'], float)
    lengths = np.linalg.norm(axes, axis=1)
    require(np.isfinite(axes).all() and lengths.min() > 1e-12 and np.linalg.norm(np.cross(*(axes/lengths[:, None]))) > 1e-8, 'TRANSFER_CONSTRAINT_COVERAGE_AXES')
    return dict(row, intended_indices=ids)


def reference(service, rows, record):
    spec = record['reference']; name = record['source_object']
    if spec['kind'] == 'initial_field':
        return dict(record, reference_status='initial_skeletal_field_not_attachment_retargeted')
    key = [service.inventory['root_id'] or service.inventory['scene_id'], spec['preview_id']]
    saved = service.store.get('transfer_previews', key); require(saved is not None, 'TRANSFER_PREVIEW_NOT_FOUND')
    summary = next((r for r in saved['source_summary'] if r['object'] == name), None)
    require(summary and all(summary[k] == rows[name][k] for k in ('topology_digest', 'geometry_digest')), 'STALE_TRANSFER_SOURCE')
    mesh = next(r for r in saved['result']['meshes'] if r['source_object'] == name)
    require(digest(mesh['vertices']) == spec['geometry_digest'], 'STALE_TRANSFER_CONSTRAINT_REFERENCE')
    return dict(record, reference_vertices=mesh['vertices'], reference_status='explicit_preview_snapshot')
