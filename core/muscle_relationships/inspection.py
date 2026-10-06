"""Read-only relationship summaries; never allocate persistent identities here."""
from copy import deepcopy
from . import store
from .identity import pair_id, domain_key


def enrich(root, value):
    try: document = store.read(root)
    except ValueError as error:
        return dict(value, relationship_revision=None, relationships=[], relationship_error=str(error), completeness='incomplete')
    if document is None: return dict(value, relationship_revision=0, relationships=[], relationship_namespace=None)
    current = value['status'] in ('complete', 'incomplete') and value.get('stacking', {}).get('publication') == 'published'
    rows = [dict(deepcopy(r), current=current) for r in document['records'].values()]
    for pair in value['pairs']:
        identity = pair_id(document['namespace'], [domain_key(pair[k]) for k in ('first', 'second')])
        pair['relationship_id'] = identity
    return dict(value, relationship_revision=document['revision'], relationships=rows, relationship_namespace=document['namespace'])
