"""Discover saved, root-scoped profiles and search their region metadata."""
from ...core.authoring.errors import AuthoringError
from ...core.authoring.references import lookup


def documents(service):
    from .queries import resolved_document
    for record in sorted(service.repository.all(), key=lambda r: r['document']['document_id']):
        try:
            yield record, resolved_document(service, record), None
        except AuthoringError as error:
            yield record, record['document'], error.diagnostic()


def summary(service):
    rows, diagnostics = [], []
    for record, document, error in documents(service):
        if error:
            diagnostics.append(dict(document_id=document['document_id'], **error))
        for name, profile in sorted(document.get('skeleton_profiles', {}).items()):
            regions = profile['regions']
            rows.append(dict(document_id=document['document_id'], draft_revision=record['draft_revision'], profile='/skeleton_profiles/'+name,
                             region_count=len(regions), sampling_count=sum(bool(r.get('sampling')) for r in regions.values()), reference_pose=profile['reference_pose']))
    return dict(journal_directory=str(service.store.directory), profiles=rows, diagnostics=diagnostics,
                region_count=sum(r['region_count'] for r in rows), scope='Saved drafts for the current root; use anatomy.catalog to search regions.')


def region_row(document, profile, name, region, inventory):
    reference = profile+'/regions/'+name
    owner = lookup(document, region['owner'])
    entity = lookup(document, owner['entity'])
    instance = owner.get('instance_id', '')
    return dict(document_id=document['document_id'], profile=profile, reference=reference, name=name, concept=region['concept'],
                side=entity['side'], owner=region['owner'], scp_id=owner['scp_id'], instance_id=instance, frame=region['frame'],
                reference_pose=region['reference_pose'], query_kind=region['query']['kind'], binding_format=binding_format(region['query']), sampling_available=bool(region.get('sampling')),
                binding_available=instance in inventory['geometry'], evidence=region['evidence'])


def binding_format(query):
    if query['kind'] != 'surface_patch':
        return 'procedural'
    signature = query['topology_digest']
    return 'polygon_vertex_indices' if signature.startswith('vertices-v2:') else 'triangle_vertex_indices' if signature.startswith('vertices-v1:') else 'legacy_triangle_indices'


def matches(row, params):
    fields = ('document_id', 'profile', 'scp_id', 'instance_id', 'side')
    if any(row[key] != params[key] for key in fields if key in params):
        return False
    if 'sampling_available' in params and row['sampling_available'] != params['sampling_available']:
        return False
    text = ' '.join(str(row[k]) for k in ('name', 'concept', 'reference')).casefold()
    return params.get('text', '').casefold() in text


def rows(service, params, diagnostics):
    for record, document, error in documents(service):
        if params.get('document_id', document['document_id']) != document['document_id']:
            continue
        if error:
            diagnostics.append(dict(document_id=document['document_id'], **error))
        for name, profile in sorted(document.get('skeleton_profiles', {}).items()):
            for key, region in sorted(profile['regions'].items()):
                try:
                    row = region_row(document, '/skeleton_profiles/'+name, key, region, service.inventory)
                    if matches(row, params):
                        yield row, document
                except AuthoringError as failure:
                    diagnostics.append(dict(document_id=document['document_id'], **failure.diagnostic()))


def catalog(service, request):
    from ...core.authoring.requirements import review_state
    params, diagnostics = request['params'], []
    result = list(rows(service, params, diagnostics))
    start, limit = params.get('offset', 0), params.get('limit', 50)
    page = result[start:start+limit]
    for row, document in page:
        row['anatomical_review'] = review_state(document, row['reference'], service.inventory)
    return dict(matches=[row for row, document in page], diagnostics=diagnostics,
                catalog=dict(total=len(result), offset=start, limit=limit, next_offset=min(start+limit, len(result)),
                             journal_directory=str(service.store.directory)))
