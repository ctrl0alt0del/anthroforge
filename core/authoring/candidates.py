"""Bounded providers propose explicit values without anatomical confidence claims."""
from copy import deepcopy
from .errors import require, AuthoringError
from .codec import digest
from .references import lookup
from .requirements import requirements


class AuthoredDefinition:
    def preflight(self, context, requirement, parameters):
        return [] if parameters.get('proposal') else ['Explicit proposal is required.']

    def propose(self, context, requirement, parameters, budget):
        budget.check()
        require(not self.preflight(context, requirement, parameters), 'CANDIDATE_INPUT_REQUIRED')
        return [dict(proposal=deepcopy(parameters['proposal']), approximations=[], inputs=parameters)]


class ExistingControl:
    def preflight(self, context, requirement, parameters):
        if requirement['need'] not in ('binding', 'control'):
            return ['Provider does not construct this requirement kind.']
        try:
            lookup(context['document'], requirement['target'])
        except AuthoringError:
            if not parameters.get('proposal'):
                return ['Target is undefined; supply its typed proposal to establish the anatomical role.']
        return []

    def propose(self, context, requirement, parameters, budget):
        require(not self.preflight(context, requirement, parameters), 'UNSUPPORTED_CAPABILITY')
        context = dict(context, seed=parameters.get('proposal', {}).get('value'))
        kind = requirement['need']
        rows = context['inventory']['instances' if kind == 'binding' else 'controls']
        selected = [r for r in rows if r['instance_id'] and (not parameters.get('instance_id') or r['instance_id'] == parameters['instance_id'])]
        result = []
        for row in selected:
            budget.check()
            value = existing_value(context, requirement, row)
            result.append(dict(proposal=dict(kind=kind, value=value), approximations=['Native identity alone does not establish anatomical meaning.'], inputs=dict(instance_id=row['instance_id'])))
        return result


def existing_value(context, requirement, row):
    old = context.get('seed') or lookup(context['document'], requirement['target'])
    value = deepcopy(old)
    value['instance_id'] = row['instance_id']
    if requirement['need'] == 'control':
        value.update(kind=row['kind'], reference_digest=row['digest'])
    else:
        value['scp_id'] = row['scp_id']
    return value


class ConstructionRule(AuthoredDefinition):
    def preflight(self, context, requirement, parameters):
        reasons = super().preflight(context, requirement, parameters)
        if parameters.get('proposal', {}).get('kind') not in ('frame', 'landmark', 'region', 'measurement'):
            reasons.append('Rule must construct a typed frame, landmark, region or measurement.')
        return reasons


def context_digest(document, inventory, revision):
    return digest([document, inventory['revision'], revision])


def requirement(document, identity):
    values = requirements(document)
    require(identity in values, 'REQUIREMENT_UNDEFINED', identity)
    return values[identity]
