"""Portable branched recipes compile parts, share root anchors, then inflate one assembly."""
from copy import deepcopy
from dataclasses import replace
import numpy as np
from .errors import AuthoringError, require
from .model import Anchor
from .anchor_contract import defaults
from .evaluation import evaluate_muscle
from .compilation import match_pins
from ..vcp.branched_surface import BranchInput, prepare_assembly, assemble
from ..vcp.prepared_inflation import inflate_assembly
from ..vcp.muscle_numeric import MuscleNumericSpec


def evaluate(document, name, construction, resolver, solver, main_transform=None):
    main = _evaluate_part(document, name, resolver, solver, main_transform)
    parts = {'main': main}
    connections = {}
    for key, definition in construction['branches'].items():
        require(key != 'main', 'RESERVED_BRANCH_NAME')
        branch = _branch(document, name, key, definition, main, resolver, solver)
        parts[key] = branch
        connections[key] = deepcopy(definition)
    require(bool(connections), 'BRANCH_REQUIRED')
    return compose(parts, connections)


def _evaluate_part(document, name, resolver, solver, transform=None):
    try:
        return evaluate_muscle(document, name, resolver, solver, plan_transform=transform)
    except AuthoringError as error:
        if error.code not in {'INFLATED_PENETRATION', 'INFLATED_SELF_INTERSECTION', 'BASE_SELF_INTERSECTION'} or not hasattr(error, 'preview'):
            raise
        result = error.preview
        result['branch_contact_diagnostic'] = error.diagnostic()
        return result


def _branch(document, name, key, definition, main, resolver, solver):
    local = deepcopy(document)
    local['recipes'][local['muscles'][name]['recipe']]['construction'] = defaults(deepcopy(definition['construction']))
    boundary = 0 if definition['boundary'] == 'first' else -1
    parent = main['fibers'][boundary]
    roots = definition['root_anchor_indices']
    require(roots == sorted(set(roots)) and 0 < roots[0] < roots[-1] < len(parent['anchors'])-1, 'INVALID_BRANCH_ROOTS')
    anchors = tuple(_anchor(parent['anchors'][i]) for i in roots)
    transform = lambda plans: _share_roots(plans, anchors, name, key)
    result = _evaluate_part(local, name, resolver, solver, transform)
    _override_inflation(result, definition.get('inflation', {}))
    return result


def _anchor(row):
    binding = row.get('surface_binding')
    binding = None if binding is None else (tuple(binding['tri_vidx']), tuple(binding['tri_weights']))
    return Anchor(row['owner'], tuple(row['point']), tuple(row['normal']), tuple(row['surface']), row['offset'], binding)


def _share_roots(plans, anchors, name, key):
    require(len(plans) == len(anchors), 'BRANCH_ROOT_COUNT_MISMATCH')
    return tuple(replace(plan, id=f'{name}.branch.{key}.u{plan.u:.12g}', anchors=(anchor, *plan.anchors[1:]))
                 for plan, anchor in zip(plans, anchors))


def _override_inflation(output, values):
    for source, destination in (('mode', 'inflation_mode'), ('amount', 'inflation_max_value')):
        if source in values:
            output['native_properties'][destination] = values[source]
    if 'control' in values:
        output['native_control_world'] = values['control']


def compose(parts, connections):
    try:
        return _compose(parts, connections)
    except ValueError as error:
        raise AuthoringError('INVALID_BRANCH_CONFIGURATION', str(error)) from error


def _compose(parts, connections):
    main = parts['main']
    rows = tuple(_points(f) for f in main['fibers'])
    branches = tuple(_input(key, data, main, parts[key], rows) for key, data in connections.items())
    assembly = prepare_assembly(rows, branches, main['native_properties']['flip_normals'])
    grids = (assembly.main, *(b.grid for b in assembly.branches))
    specs = tuple(_spec(part, grid) for part, grid in zip(parts.values(), grids))
    inflated = inflate_assembly(assembly, specs)
    base, faces = assemble(assembly); volume, _ = assemble(assembly, *inflated)
    result = deepcopy(main)
    result.update(base=base.tolist(), inflated=volume.tolist(), faces=faces.tolist(), branch_parts=parts,
                  branch_connections=connections, fibers=[f for p in parts.values() for f in p['fibers']],
                  measurement_scope='main_part_before_connector', assembly_contact_checked=False)
    return result


def _points(fiber):
    return np.asarray(fiber['points'], dtype=np.float32).astype(np.float64)


def _input(key, data, main, child, rows):
    boundary = 0 if data['boundary'] == 'first' else -1
    parent = main['fibers'][boundary]
    pins = match_pins(rows[boundary], np.asarray([a['point'] for a in parent['anchors']]), False)
    roots = tuple(int(pins[i]) for i in data['root_anchor_indices'])
    return BranchInput(key, boundary, roots, tuple(_points(f) for f in child['fibers']),
                       data.get('width', .25), data.get('fullness', 0.))


def _spec(part, grid):
    return MuscleNumericSpec(target_count=grid.shape[1], densify=False, closed_u=False,
        close_across_fibers=False, topology_flip_normals=False, closed_v=False,
        control_world=tuple(part['native_control_world']), **part['native_properties'])
