"""Proposal, preview, revision and adoption are distinct operations."""
from copy import deepcopy
from ...core.authoring.codec import digest
from ...core.authoring.errors import require, AuthoringError
from ...core.authoring.patching import apply_patch
from ...core.authoring.validation import document as validate_document
from ...core.authoring import candidates, substrate
from ...core.authoring.requirements import RequirementResolver
from ...core.authoring.regions import RegionEvaluator
from ...core.authoring.preview import svg, scene_bounds
from ...core.authoring.model import Budget
from . import drafts


def propose_binding(service, request):
    params, record = request['params'], service.load(request['params'])
    service.check(params, record)
    spec = candidates.requirement(record['document'], params['requirement'])
    provider = service.providers.get(params['provider'])
    context = dict(document=record['document'], inventory=service.inventory)
    missing = provider.preflight(context, spec, params['parameters'])
    if missing:
        return dict(status='unresolved', search_state='incomplete', missing=missing, candidates=[])
    rows = provider.propose(context, spec, params['parameters'], Budget())
    saved = [save_candidate(service, record, params['requirement'], params['provider'], row) for row in rows]
    return dict(search_state='complete', candidates=[summary(row) for row in saved], ranking='Unranked: candidates have no shared anatomical scoring basis.')


def save_candidate(service, record, requirement_id, provider, row):
    spec = candidates.requirement(record['document'], requirement_id)
    patch = [dict(op='add', path=spec['target'], value=row['proposal']['value'])]
    require(row['proposal']['kind'] == spec['need'], 'CANDIDATE_KIND_MISMATCH')
    document = validate_document(apply_patch(record['document'], patch))
    result = RequirementResolver(document, service.inventory).row(requirement_id, spec)
    value = dict(requirement=requirement_id, provider=provider, draft_revision=record['draft_revision'], document_id=document['document_id'], inputs_digest=candidates.context_digest(record['document'], service.inventory, record['draft_revision']), patch=patch, checks=result, **row)
    value.update(method=provider, constraints=spec['constraints'], coverage=dict(target=spec['target'], state=result['state']))
    value['id'] = digest(value)
    value['previews'] = candidate_previews(service, document, spec, row['proposal'])
    service.store.put('v04_candidates', [document['document_id'], value['id']], value)
    return value


def candidate_previews(service, document, spec, proposal):
    try:
        polygons = candidate_geometry(service, document, spec, proposal)
        return [service.store.asset(dict(polygons=polygons, target=spec['target'])), service.store.image(svg(polygons, 'Binding candidate — common scene scale', scene_bounds(service.inventory)))]
    except AuthoringError as error:
        return [service.store.asset(dict(unresolved=error.diagnostic()))]


def candidate_geometry(service, document, spec, proposal):
    kind, value = proposal['kind'], proposal['value']
    if kind == 'region':
        return RegionEvaluator(document, service.inventory).evaluate(spec['target'])['polygons']
    if kind == 'landmark':
        point = substrate.world(substrate.frame(document, service.inventory, value['frame']), value['q']).tolist()
        return [[point]]
    if kind in ('frame', 'measurement'):
        from .previews import typed_geometry
        return typed_geometry(document, service.inventory, spec, proposal)
    return native_geometry(service.inventory, value.get('instance_id'))


def native_geometry(inventory, key):
    data = inventory['geometry'].get(key)
    if data:
        import numpy as np
        vertices, matrix = np.array(data['vertices']), np.array(data['matrix'])
        world = vertices @ matrix[:3, :3].T+matrix[:3, 3]
        return world[np.array(data['triangles'], int)].tolist()
    return [[p] for row in inventory['controls'] if row['instance_id'] == key for p in row['points']]


def summary(value):
    return {k: value[k] for k in ('id', 'document_id', 'provider', 'requirement', 'checks', 'previews', 'approximations')}


def get_candidate(service, params):
    value = service.store.get('v04_candidates', [params['document_id'], params['candidate_id']])
    require(value is not None, 'CANDIDATE_NOT_FOUND')
    return value


def inspect_candidate(service, request):
    value = get_candidate(service, request['params'])
    return dict(candidate=value, assets=value['previews'])


def revise_candidate(service, request):
    params, record = request['params'], service.load(request['params'])
    service.check(params, record)
    old = get_candidate(service, params)
    require(old['inputs_digest'] == candidates.context_digest(record['document'], service.inventory, record['draft_revision']), 'STALE_CANDIDATE')
    row = dict(proposal=params['proposal'], inputs=dict(previous=old['id']), approximations=old['approximations'])
    value = save_candidate(service, record, old['requirement'], 'authored_definition.v1', row)
    return dict(candidate=summary(value))


def adopt_binding(service, request):
    params, record = request['params'], service.load(request['params'])
    replay = service.repository.replay(record, request)
    if replay:
        return drafts.receipt_response(service, record, replay)
    service.check(params, record)
    value = get_candidate(service, params)
    require(value['inputs_digest'] == candidates.context_digest(record['document'], service.inventory, record['draft_revision']), 'STALE_CANDIDATE')
    require(params['mode'] == 'provisional' or value['checks']['state'] == 'resolved', 'CANDIDATE_UNRESOLVED')
    document = validate_document(apply_patch(record['document'], value['patch']))
    provisional = set(record.get('provisional', []))
    target = value['patch'][0]['path']
    provisional.add(target) if params['mode'] == 'provisional' else provisional.discard(target)
    extra = dict(provisional=sorted(provisional), adoptions=record.get('adoptions', [])+[dict(candidate=value['id'], target=target, mode=params['mode'])])
    return drafts.commit(service, request, document, record, value['patch'], extra)
