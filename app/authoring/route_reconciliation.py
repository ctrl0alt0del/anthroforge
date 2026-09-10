"""Adopt attachment edits as explicit region-relative route overrides."""
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.references import lookup
from ...core.authoring.substrate import frame, coordinates
from .construction import instance_value


def patches(service, record, change):
    operations, unresolved = [], []
    before, after = change['baseline'].get('fibers', {}), change['current'].get('fibers', {})
    for name, ids in record['published']['native_ids'].items():
        for fiber, native_id in ids['fibers'].items():
            if before.get(native_id) == after.get(native_id):
                continue
            try:
                operations.append(fiber_patch(service, record, name, fiber, before.get(native_id), after.get(native_id)))
            except AuthoringError as error:
                unresolved.append(dict(subject=fiber, diagnostic=error.diagnostic()))
    return combined(operations), unresolved


def combined(operations):
    paths = {}
    for operation in operations:
        paths.setdefault(operation['path'], {}).update(operation['value'])
    return [dict(op='add', path=path, value=value) for path, value in paths.items()]


def fiber_patch(service, record, name, fiber, before, after):
    require(before and after, 'NATIVE_ENTITY_REMOVED')
    require(signature(before) != signature(after), 'ROUTE_INVERSE_UNAVAILABLE')
    document = record['document']
    instance = instance_value(document, name)
    require(name in document.get('instances', {}), 'ASSEMBLY_ROUTE_OVERRIDE_UNAVAILABLE')
    baseline = record['published'].get('authored_baseline', document)
    require(instance == instance_value(baseline, name), 'RECONCILIATION_DRAFT_CONFLICT')
    current = service.native_edits.attachment_points(after)
    regions = region_order(record, name, fiber)
    require(len(current) == len(regions), 'ROUTE_OVERRIDE_TOPOLOGY_CHANGED')
    anchors = [relative_anchor(document, service.inventory, r, a) for r, a in zip(regions, current)]
    overrides = dict(instance.get('route_overrides', {}))
    overrides[fiber] = dict(anchors=anchors, evidence=dict(basis='designer_authored', sources=[], note='Explicit native attachment correction in the owner frame.'))
    return dict(op='add', path='/instances/'+name+'/route_overrides', value=overrides)


def signature(record):
    v, c = record['values'], record['collections']
    return [v.get(k) for k in ('topology_mode', 'a_parent_id', 'a_attach_param', 'b_parent_id', 'b_attach_param')]+[c.get(k) for k in ('mid_touches', 'loop_anchors')]


def region_order(record, name, fiber):
    compiled = record['compiled']
    native = compiled['ir']['document']
    muscle = native['muscles'][name]
    construction = native['recipes'][muscle['recipe']]['construction']
    stations = construction['stations']
    if construction['kind'] == 'closed_loft':
        row = next(f for f in compiled['outputs'][name]['fibers'] if f['id'] == fiber)
        loop = next(l for l in construction['loops'] if l['u'] == row['u'])
        stations = [loop['anchors'][s['id']] for s in stations]
    return [compiled['ir']['domains'][muscle['region_bindings'][s['region_role']]['region']] for s in stations]


def relative_anchor(document, inventory, reference, attachment):
    region = lookup(document, reference)
    chart = frame(document, inventory, region['frame'])
    require(chart['owner']['instance_id'] == attachment['owner'], 'ROUTE_OVERRIDE_OWNER_CHANGED')
    result = dict(region=reference, seed=coordinates(chart, attachment['point']).tolist(), offset=attachment['offset'])
    if attachment.get('surface_binding'):
        result['surface_binding'] = attachment['surface_binding']
    return result
