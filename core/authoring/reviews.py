"""Review evidence binds authored dependencies and relevant reference geometry."""
from .codec import digest
from .errors import AuthoringError
from .references import lookup, references, fingerprint


def inputs(document, inventory, reference):
    try:
        authored = fingerprint(document, reference)
        ids = dependencies(document, reference)
        geometry = {k: v for k, v in inventory.get('geometry', {}).items() if k in ids}
        controls = {c['instance_id']: c['digest'] for c in inventory.get('controls', []) if c['instance_id'] in ids}
        return digest([authored, geometry, controls, inventory.get('reference_pose')])
    except AuthoringError:
        return ''


def dependencies(document, reference):
    pending, visited, result = [reference], set(), set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        value = lookup(document, current)
        result.update(instance_ids(value))
        pending.extend(references(value)-visited)
    return result


def instance_ids(value):
    if isinstance(value, dict):
        own = {value['instance_id']} if 'instance_id' in value else set()
        return own.union(*(instance_ids(v) for v in value.values()))
    return set().union(*(instance_ids(v) for v in value)) if isinstance(value, list) else set()


def aggregate(document, inventory):
    from .requirements import review_state
    subjects = ['/instances/'+k for k in document.get('instances', {})]
    states = [review_state(document, s, inventory) for s in subjects]
    return 'accepted' if states and all(s == 'accepted' for s in states) else 'rejected' if 'rejected' in states else 'unreviewed'
