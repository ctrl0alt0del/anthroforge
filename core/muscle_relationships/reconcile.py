"""Pure reconciliation keeps durable intent separate from transient evidence."""
from copy import deepcopy
from .identity import domain_key, pair_id, token
from .fingerprints import digest
from .store import new_record


def evidence_signature(pair, manifest):
    return digest((manifest['version'], {k: manifest['settings'][k] for k in ('min_projected_area', 'epsilon')},
        [manifest['domains'][token(k)]['order'] for k in pair]))


def intent_status(intent, manifest):
    region = intent.get('region')
    if not region: return None
    stamp = manifest['domains'].get(token(region['domain']))
    if stamp is None: return 'missing_reference'
    compatible = region['version'] == 'base-ray-material-policy-1' and manifest['version'] == 'base-ray-material-policy-2'
    if region['version'] != manifest['version'] and not compatible: return 'selection_algorithm_changed'
    if stamp['topology'] != region['topology']: return 'selection_topology_changed'
    return None


def state(row, manifest):
    if row.get('unresolved_import'): return 'missing_reference'
    if any(token(k) not in manifest['domains'] for k in row['pair']): return 'missing_reference'
    intent = row.get('intent', {})
    if intent.get('excluded'): return 'excluded'
    problem = intent_status(intent, manifest)
    if problem: return problem
    if row.get('policy', {}).get('status') not in (None, 'allowed'): return row['policy']['status']
    if intent.get('mode') == 'explicit':
        effective = row.get('effective_order', {})
        return 'active' if effective.get('status') == 'supported' else 'geometric_' + row.get('status', 'not_detected')
    if row.get('status') != 'supported': return 'geometric_' + row.get('status', 'not_detected')
    if intent.get('cover') and intent['cover'] != row['covering']: return 'manual_order_conflict'
    return 'active'


def evidence_row(document, pair, manifest):
    keys = sorted([domain_key(pair[k]) for k in ('first', 'second')]); identity = pair_id(document['namespace'], keys)
    old = document['records'].get(identity, new_record(document['namespace'], keys)); order = pair['order']
    value = deepcopy(old); signature = evidence_signature(keys, manifest)
    value.update(status=order['status'], diagnostic=order.get('diagnostic', ''),
        underlying=domain_key(order['underlying']) if order['underlying'] else None,
        covering=domain_key(order['covering']) if order['covering'] else None,
        policy=deepcopy(pair.get('policy', {})), effective_order=deepcopy(pair.get('effective_order', {})), evidence_signature=signature,
        evidence_reused=old.get('evidence_signature') == signature and old.get('status') == order['status'])
    return value


def reconcile(document, manifest, summary):
    value = deepcopy(document); rows = value['records']; seen = set()
    for pair in summary['pairs']:
        row = evidence_row(document, pair, manifest); rows[row['id']] = row; seen.add(row['id'])
        pair['relationship_id'] = row['id']
    for identity, row in rows.items():
        if identity not in seen: row.update(status='not_detected', effective_order={}, policy={}, evidence_reused=False)
        row['state'] = state(row, manifest)
    value['manifest'] = manifest
    return value


def restoration_state(document, row, manifest):
    if row.get('unresolved_import') or any(token(k) not in manifest['domains'] for k in row['pair']): return 'missing_reference'
    invalid = intent_status(row.get('intent', {}), manifest)
    if invalid: return invalid
    if row.get('evidence_signature') != evidence_signature(row['pair'], manifest): return 'requires_rescan'
    old = document['manifest']
    same = old['settings'] == manifest['settings'] and all(old['domains'].get(token(k)) == manifest['domains'][token(k)] for k in row['pair'])
    return 'verified_metadata' if same else 'order_valid_requires_refresh'
