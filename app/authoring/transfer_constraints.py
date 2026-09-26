"""Constraint resolution strategies; the app depends on records, not a numerical solver."""
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.codec import digest
from . import transfer_bands, transfer_constraint_domains as domains


def attachment(service, rows, names, spec, row):
    band = dict(row['selection'], id=row['id'], vertex_indices=row['vertex_indices'], target=row['target'])
    band.update({k: row[k] for k in ('mapping', 'target_bindings') if k in row})
    config = dict(spec, protected_bands=[], attachment_bands=[band])
    target = transfer_bands.resolve(service, rows, names, config)[0]
    return dict(row, attachment=target)


def reference(service, rows, names, spec, row):
    return domains.reference(service, rows, row)


def clearance(service, rows, names, spec, row):
    require(set(row['obstacle_instance_ids']) <= set(spec['obstacle_instance_ids']), 'TRANSFER_SHAPE_OBSTACLES')
    return row


def identity(service, rows, names, spec, row):
    return row


RESOLVERS = dict(attachment=attachment, protection=reference, guide=reference, shape=identity, clearance=clearance)


def configure(service, rows, names, spec):
    records = spec['constraints']; require(records['version'] == 'transfer_constraints.v1', 'TRANSFER_CONSTRAINT_VERSION')
    require(not spec.get('protected_bands') and not spec.get('attachment_bands'), 'TRANSFER_CONSTRAINT_LEGACY_MIX')
    values = records['items']; require(len({r['id'] for r in values}) == len(values), 'TRANSFER_CONSTRAINT_DUPLICATE_ID')
    resolved = [resolve(service, rows, names, spec, r) for r in sorted(values, key=lambda r: r['id'])]
    masks = {name: np.zeros(len(rows[name]['geometry']['vertices']), np.int32) for name in names}
    for row in resolved:
        if row['type'] in ('attachment', 'protection') and row.get('enabled', True):
            masks[row['source_object']][row['vertex_indices']] = 1
    require(all(m.any() for m in masks.values()), 'TRANSFER_SHAPE_MISSING_PART_BAND')
    return dict(spec, _constraints=resolved), masks


def resolve(service, rows, names, spec, record):
    require(record['type'] in RESOLVERS, 'TRANSFER_CONSTRAINT_TYPE')
    row = domains.coverage(rows, domains.domain(rows, names, record))
    return RESOLVERS[row['type']](service, rows, names, spec, row)


def verify(service, record):
    from .transfers import capture
    spec = record['definition']['shape_preservation']
    if 'constraints' not in spec:
        return
    names = record['definition']['source_objects']; rows = capture(service, names)
    resolved, _masks = configure(service, rows, names, spec)
    expected = record['result']['shape_preservation']['constraint_resolution_digest']
    require(digest(resolved['_constraints']) == expected, 'STALE_TRANSFER_CONSTRAINT_REFERENCE')
