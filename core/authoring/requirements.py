"""Dependency diagnostics independently report resolution and review state."""
from .errors import AuthoringError, require
from .references import references, lookup, affected
from . import substrate
from .regions import RegionEvaluator

STATES = {'REFERENCE_UNDEFINED': 'undefined', 'BINDING_UNBOUND': 'unbound', 'BINDING_AMBIGUOUS': 'ambiguous', 'BINDING_STALE': 'stale', 'CONTROL_REBIND_REQUIRED': 'stale', 'CONTROL_UNAVAILABLE': 'unbound', 'SURFACE_DOMAIN_UNAVAILABLE': 'unsupported', 'UNSUPPORTED_CAPABILITY': 'unsupported'}


def requirements(document):
    explicit = document.get('requirements', {})
    result = dict(explicit)
    for ref in sorted(references({k: v for k, v in document.items() if k != 'requirements'})):
        if not any(r['target'] == ref for r in result.values()):
            result[ref] = dict(target=ref, need='reference', depends_on=[], consumers=affected(document, [ref]), constraints=[], required_state='resolved')
    return result


class RequirementResolver:
    def __init__(self, document, inventory, capabilities=(), provisional=()):
        self.document, self.inventory, self.capabilities = document, inventory, capabilities
        self.provisional, self.cache = set(provisional), {}

    def resolve(self, reference, active=()):
        if reference in self.cache:
            return self.cache[reference]
        if reference in active:
            return dict(state='invalid', code='DEPENDENCY_CYCLE', causes=[list(active)+( [reference])])
        try:
            value = lookup(self.document, reference)
            require(reference not in self.provisional, 'BINDING_UNBOUND', 'Provisional binding')
            deps = [(r, self.resolve(r, active+(reference,))) for r in sorted(references(value))]
            failed = [(r, v) for r, v in deps if v['state'] != 'resolved']
            result = blocked(reference, failed) if failed else self.inspect(reference, value)
        except AuthoringError as error:
            result = dict(state=STATES.get(error.code, 'invalid'), code=error.code, causes=[[reference]], diagnostic=error.diagnostic())
        self.cache[reference] = result
        return result

    def inspect(self, reference, value):
        kind = reference.split('/')[-2] if reference.count('/') > 1 else ''
        if kind == 'evaluation_profiles':
            check_evaluation(value, self.inventory, self.capabilities)
        elif kind == 'bindings':
            substrate.binding(self.document, self.inventory, reference)
        elif kind == 'frames':
            substrate.frame(self.document, self.inventory, reference)
        elif kind == 'controls':
            substrate.control(self.document, self.inventory, reference)
        elif kind == 'regions':
            require(RegionEvaluator(self.document, self.inventory).evaluate(reference)['area'] > 0, 'REGION_EMPTY')
        elif kind in ('measurements', 'recipes', 'shape_presets'):
            inspect_intent(self.document, self.inventory, reference, value, kind)
        return dict(state='resolved', code='RESOLVED', causes=[])
    def report(self):
        rows = [self.row(key, spec) for key, spec in requirements(self.document).items()]
        earliest = sorted({path[-1] for row in rows for path in row['causes']})
        from .reviews import inputs
        return dict(requirements=rows, actionable=earliest, resolved=all(r['state'] == 'resolved' for r in rows), review_inputs={r['target']: inputs(self.document, self.inventory, r['target']) for r in rows})

    def row(self, identity, spec):
        result = dict(self.resolve(spec['target']))
        dependencies = [(r, self.resolve(r)) for r in spec.get('depends_on', [])]
        if result['state'] == 'resolved':
            failed = [(r, v) for r, v in dependencies if v['state'] != 'resolved']
            result = blocked(spec['target'], failed) if failed else constrained(self, spec, result)
        return dict(id=identity, target=spec['target'], consumers=sorted(set(spec['consumers']+affected(self.document, [spec['target']]))), review=review_state(self.document, spec['target'], self.inventory), **result)


def check_evaluation(value, inventory, capabilities):
    require(value['reference_pose'] == inventory['reference_pose'], 'REFERENCE_POSE_MISMATCH')
    require(not set(value['required_capabilities'])-set(capabilities), 'UNSUPPORTED_CAPABILITY')


def inspect_intent(document, inventory, reference, value, kind):
    if kind == 'measurements':
        measurement(document, inventory, reference)
    elif kind == 'recipes':
        recipe_constraints(value)
    else:
        for target in value['targets']:
            require(target['metric'] not in ('area', 'volume') or target['closure'] != 'none', 'UNSUPPORTED_CAPABILITY', 'This metric requires an explicit supported closure.')


def recipe_constraints(recipe):
    from .lowering import strategy
    construction = strategy(recipe, dict(parameters={}))
    conformed = construction.get('boundary_conformance', {}).get('stations', [])
    for station in construction.get('stations', []):
        if station['id'] in conformed:
            offset = station['offset']
            require(not offset.get('value', offset.get('fraction', 0)), 'BOUNDARY_OFFSET_UNSUPPORTED', station['id']+' has an offset; native station conformance currently requires zero offset.')


def review_state(document, reference, inventory=None):
    from .reviews import inputs
    rows = [r for r in document.get('reviews', {}).values() if r['subject'] == reference]
    if not rows:
        return 'unreviewed'
    try:
        current = inputs(document, inventory or {}, reference)
        valid = [r['state'] for r in rows if r['input_digest'] == current]
        return 'rejected' if 'rejected' in valid else 'accepted' if 'accepted' in valid else 'stale'
    except AuthoringError:
        return 'stale'


def blocked(reference, failed):
    return dict(state='blocked', code='PREREQUISITE_UNRESOLVED', causes=[[reference]+path for _, value in failed for path in value['causes']])


def constrained(resolver, spec, result):
    try:
        value = lookup(resolver.document, spec['target'])
        for c in spec['constraints']:
            actual = constraint_value(resolver, value, c['kind'])
            require(c['value'] in actual if c['kind'] == 'capability' else actual == c['value'], 'REQUIREMENT_CONSTRAINT', c['kind'])
        return result
    except AuthoringError as error:
        return dict(state='unsupported' if any(c['kind'] == 'capability' for c in spec['constraints']) else 'invalid', code=error.code, causes=[[spec['target']]])


def constraint_value(resolver, value, kind):
    if kind == 'capability':
        return resolver.capabilities
    if kind == 'control_kind':
        return value.get('kind')
    if kind == 'dimension':
        unit = value.get('quantity', {}).get('unit', 'scene')
        return {'scene2': 'area', 'scene3': 'volume', 'ratio': 'ratio'}.get(unit, 'length')
    entity = lookup(resolver.document, value['entity']) if value.get('entity') else value
    return entity.get('side', 'unknown')


def measurement(document, inventory, reference):
    import numpy as np
    value = lookup(document, reference)
    if value['kind'] == 'value':
        quantity = value['quantity']
        if quantity['unit'] in ('mm', 'cm', 'm'):
            profile = lookup(document, '/'.join(reference.split('/')[:3]))
            require(profile.get('calibration'), 'CALIBRATION_REQUIRED')
        return quantity
    a, b = [lookup(document, value[k]) for k in ('first', 'second')]
    points = [substrate.world(substrate.frame(document, inventory, p['frame']), p['q']) for p in (a, b)]
    return dict(value=float(np.linalg.norm(points[0]-points[1])), unit='scene', evidence=value['evidence'])
