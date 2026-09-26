"""Compile resolved records into batched native inputs and publish located feedback."""
import numpy as np
from ...core.authoring.codec import digest
from ...core.authoring.transfer_constraints_native import fit
from ...core.authoring.transfer_quality import diagnostic
from . import transfer_bands


def compile_record(record, mesh, offset, total, initial):
    row = dict(record); ids = np.asarray(row['vertex_indices'], int); targets = np.zeros((total, 3))
    if row['type'] in ('guide', 'protection'):
        targets[offset:offset+len(mesh['vertices'])] = row.get('reference_vertices', initial[offset:offset+len(mesh['vertices'])])
    if 'attachment' in row:
        targets[offset+ids] = row['attachment']['targets']
        row['target_quality'] = transfer_bands.target_quality(mesh, row['attachment'])
    row.update(indices=(offset+ids).tolist(), allowed=list(range(offset, offset+len(mesh['vertices']))), targets=targets)
    row['intended'] = (offset+np.asarray(row.get('intended_indices', ids), int)).tolist()
    return row


def calculate(sources, result, bones, masks, spec):
    from .shape_transfer import pack
    source, initial, faces, fixed, starts = pack(sources, result['meshes'], masks)
    meshes = {r['source_object']: (r, int(i)) for r, i in zip(result['meshes'], starts)}
    records = [compile_record(r, *meshes[r['source_object']], len(source), initial) for r in spec['_constraints']]
    owners = np.concatenate([np.full(len(r['vertices']), i, np.int32) for i, r in enumerate(result['meshes'])])
    orientations = {r['quality']['orientation'] for r in result['meshes']}
    from ...core.authoring.errors import require
    require(len(orientations) == 1, 'TRANSFER_SHAPE_ORIENTATION')
    candidate = fit(source, initial, faces, fixed, bones, records, owners, spec.get('settings'), orientations.pop())
    targets = initial.copy()
    for row in records:
        if row['type'] in ('attachment', 'protection') and row.get('enabled', True):
            targets[row['indices']] = row['targets'][row['indices']]
    return candidate, records, (source, initial, faces, fixed, starts, targets)


def report(row, arrays, index):
    factors, residuals, movement, summaries, coverage = arrays; values = summaries[index]
    ids = np.asarray(row['allowed'], int); weights = factors[index, ids]; stations = coverage[index]
    enabled = row.get('enabled', True) and (row['type'] in ('attachment', 'protection') or row.get('weight', 1.) > 0)
    minimum = row.get('coverage', {}).get('minimum_fraction', 0.)
    covered = values[3] >= minimum and all(v >= minimum for v in stations if v >= 0)
    collapsed = row.get('target_quality', {}).get('target_collapsed_triangle_indices', [])
    passed = values[0] <= row['tolerance'] and covered and not collapsed
    return dict(id=row['id'], type=row['type'], source_object=row['source_object'], enabled=row.get('enabled', True), active=enabled,
        status=('satisfied' if passed else 'unresolved') if enabled else 'disabled', tolerance=row['tolerance'],
        requested_vertex_indices=row['vertex_indices'], intended_vertex_indices=row.get('intended_indices', row['vertex_indices']),
        active_vertex_indices=np.flatnonzero(weights > 0).tolist(), influence=weights.tolist(), residuals=residuals[index, ids].tolist(),
        **report_metrics(row, values, stations, minimum, movement[index, ids], ids))


def report_metrics(row, values, stations, minimum, movement, ids):
    return dict(movement_from_initial=movement.tolist(), maximum_residual=float(values[0]), maximum_movement=float(values[1]), mean_squared_residual=float(values[5]),
        coverage=dict(vertex_fraction=float(values[2]), lumped_area_fraction=float(values[3]), station_fractions=stations.reshape(2, 16).tolist(), minimum_fraction=minimum),
        targets=row['targets'][ids].tolist() if row['type'] in ('attachment', 'guide', 'protection') else [],
        initial_maximum_target_error=float(values[6]), reference_status=row.get('reference_status', 'not_applicable'), target_quality=row.get('target_quality', {}),
        enforcement=row['enforcement'], weight=row.get('weight', 1.), falloff=row.get('falloff', 0.),
        residual_measure='maximum_incident_edge_log_strain' if row['type'] == 'shape' else 'world_distance')


def refine(scene, sources, result, supports, masks, spec):
    from .shape_transfer import update_mesh
    from .collision_correction import obstacles
    from .shape_transfer_review import review, finish
    bones, checks = obstacles(scene, supports, spec['tolerance'])
    candidate, records, data = calculate(sources, result, bones, masks, spec)
    _source, initial, faces, fixed, starts, targets = data
    audit = review(targets, candidate['vertices'], faces, fixed, bones, spec)
    for row, begin, end in zip(result['meshes'], starts[:-1], starts[1:]):
        row['initial_vertices'] = initial[begin:end].tolist(); update_mesh(row, candidate, targets, fixed, int(begin), int(end), initial)
    result['shape_preservation'] = dict(family_id=spec['family_id'], fitting=candidate['fitting'], obstacle_quality=checks,
        source_order=[r['source_object'] for r in result['meshes']], vertex_offsets=starts.tolist(), **audit)
    result = finish(result)
    return finish_constraints(result, records, candidate, spec)


def finish_constraints(result, records, candidate, spec):
    data = result['shape_preservation']; reports = [report(r, candidate['constraint_arrays'], i) for i, r in enumerate(records)]
    data.update(constraints=reports, constraint_resolution_digest=digest(spec['_constraints']), configuration=spec['constraints'])
    for row in reports:
        if row['status'] == 'unresolved':
            result['diagnostics'].append(diagnostic('TRANSFER_CONSTRAINT_UNSATISFIED', row['id']+': inspect residual, coverage and target-face reports.', 'error'))
    result['method'] = 'shared_cubic_rbf_local_constraints.v1'
    result['validation']['constraints'] = 'unresolved' if any(r['status'] == 'unresolved' for r in reports) else 'satisfied'
    result['status'] = 'unresolved' if any(d['severity'] == 'error' for d in result['diagnostics']) else 'success'
    return result
