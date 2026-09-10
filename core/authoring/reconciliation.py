"""Unique inverse mappings for native inflation edits."""
from copy import deepcopy
from .errors import require
from .references import lookup

FIELDS = {'inflation_max_value': ('amount',), 'inflation_falloff_radius': ('radius',), 'inflation_direction_depth': ('direction_depth',), 'inflation_boundary_strength': ('boundary', 'strength'), 'inflation_boundary_power': ('boundary', 'power'), 'inflation_boundary_band': (), 'inflation_enabled': ('enabled',), 'flip_normals': ('flip_normals',), 'inflation_falloff_type': ('falloff',), 'inflation_mode': ('mode',)}


def semantic_patch(document, published, change):
    operations, unresolved = [], []
    for name, ids in published['native_ids'].items():
        first = change['baseline'].get('muscles', {}).get(ids['muscle'])
        last = change['current'].get('muscles', {}).get(ids['muscle'])
        if first and last:
            check_conflict(document, published, name, first, last)
            operations.extend(muscle_patch(document, name, ids['muscle'], first, last))
    for group in ('fiber_surfaces',):
        if change['baseline'].get(group) != change['current'].get(group):
            unresolved.append(group)
    return operations, unresolved


def check_conflict(document, published, name, before, after):
    if not any(before['values'].get(k) != after['values'].get(k) for k in FIELDS):
        return
    baseline = published.get('authored_baseline', document)
    first, last = [lookup(d, '/instances/'+name) for d in (baseline, document)]
    require(first['shape'] == last['shape'], 'RECONCILIATION_DRAFT_CONFLICT')
    require(lookup(baseline, first['shape']) == lookup(document, last['shape']), 'RECONCILIATION_DRAFT_CONFLICT')


def muscle_patch(document, name, native_id, before, after):
    changes = {k: after['values'][k] for k in FIELDS if before['values'].get(k) != after['values'].get(k)}
    if not changes:
        return []
    instance = lookup(document, '/instances/'+name)
    preset = deepcopy(lookup(document, instance['shape']))
    from .lowering import shape_intent
    shape_intent(preset['native'], preset.pop('intent', {}))
    for key, value in changes.items():
        assign_change(preset['native'], key, value, before['values'].get(key))
    preset['evidence'] = dict(basis='designer_authored', sources=[], note='Explicit reconciliation of native inflation controls.')
    key = 'adopted_'+native_id
    return [dict(op='add', path='/shape_presets/'+key, value=preset), dict(op='replace', path='/instances/'+name+'/shape', value='/shape_presets/'+key)]


def assign_change(preset, key, value, previous):
    if key != 'inflation_boundary_band':
        return assign_inverse(preset, FIELDS[key], value, previous)
    require(previous is not None and .1 < previous < 16., 'INVERSE_MAPPING_UNAVAILABLE')
    boundary = preset['boundary']
    scaled = {axis: boundary[axis] * value / previous for axis in ('along', 'across')}
    require(all(0 <= number <= .5 for number in scaled.values()), 'INVERSE_MAPPING_UNAVAILABLE')
    boundary.update(scaled)


def assign_inverse(preset, path, value, previous):
    node = preset
    for part in path[:-1]:
        node = node[part]
    key, old = path[-1], node.get(path[-1])
    if isinstance(old, dict):
        if 'fraction' in old:
            require(previous not in (None, 0), 'INVERSE_MAPPING_UNAVAILABLE')
            old['fraction'] *= value/previous
        else:
            require(old['unit'] == 'scene', 'INVERSE_MAPPING_UNAVAILABLE')
            old['value'] = value
    else:
        node[key] = {'CTRL_POINT': 'control_point', 'DISTRIBUTED': 'distributed'}.get(value, value.lower()) if isinstance(value, str) else value
