"""Strict structural validation before any relationship state is replaced."""
from uuid import UUID
from .identity import pair_id, token


def require(condition, code):
    if not condition: raise ValueError(code)


def domain(value):
    require(isinstance(value, (list, tuple)) and len(value) == 3, 'RELATIONSHIP_DOMAIN')
    require(isinstance(value[0], str) and bool(value[0]) and value[1] in ('source', 'mirror')
        and value[2] in ('A', 'B'), 'RELATIONSHIP_DOMAIN')


def region(value, pair):
    require(isinstance(value, dict) and set(value) == {'domain', 'faces', 'topology', 'version'}, 'RELATIONSHIP_REGION')
    require(value['domain'] in pair, 'RELATIONSHIP_REGION_DOMAIN')
    require(isinstance(value['faces'], list) and 0 < len(value['faces']) <= 2000000, 'RELATIONSHIP_REGION_FACES')
    for face in value['faces']:
        require(isinstance(face, (list, tuple)) and len(face) == 2 and all(type(v) is int and v >= 0 for v in face), 'RELATIONSHIP_REGION_FACE')
    require(all(isinstance(value[k], str) and value[k] for k in ('topology', 'version')), 'RELATIONSHIP_REGION_STAMP')


def intent(value, pair):
    require(isinstance(value, dict) and not set(value) - {'excluded', 'cover', 'region'}, 'RELATIONSHIP_INTENT')
    require(type(value.get('excluded', False)) is bool, 'RELATIONSHIP_EXCLUDED')
    if value.get('cover') is not None: require(value['cover'] in pair, 'RELATIONSHIP_COVER')
    if value.get('region') is not None:
        region(value['region'], pair)
        require(value.get('cover') == value['region']['domain'], 'RELATIONSHIP_REGION_COVER')


def record(value, identity, namespace):
    require(isinstance(value, dict), 'RELATIONSHIP_RECORD')
    pair = value.get('pair')
    require(isinstance(pair, list) and len(pair) == 2, 'RELATIONSHIP_PAIR')
    for item in pair: domain(item)
    require(pair[0] != pair[1], 'RELATIONSHIP_SELF_PAIR')
    require(value.get('id') == identity == pair_id(namespace, pair), 'RELATIONSHIP_ID')
    require(value.get('origin') in ('automatic', 'manual', 'imported'), 'RELATIONSHIP_ORIGIN')
    intent(value.get('intent', {}), pair)
    for name in ('underlying', 'covering'):
        if value.get(name) is not None: require(value[name] in pair, 'RELATIONSHIP_EVIDENCE_DOMAIN')
    evidence(value)


def evidence(value):
    for name in ('status', 'state'):
        require(isinstance(value.get(name), str) and bool(value[name]), 'RELATIONSHIP_EVIDENCE_STATUS')
    require(isinstance(value.get('diagnostic', ''), str), 'RELATIONSHIP_DIAGNOSTIC')
    policy = value.get('policy', {})
    require(isinstance(policy, dict) and policy.get('status') in (None, 'allowed', 'excluded', 'manual_order_conflict', 'stale_selected_region'), 'RELATIONSHIP_POLICY')
    if value.get('unresolved_import'):
        source = value['unresolved_import']; require(isinstance(source, dict), 'RELATIONSHIP_IMPORT_SOURCE')
        try: UUID(source['namespace'])
        except (KeyError, ValueError, TypeError, AttributeError) as error: raise ValueError('RELATIONSHIP_IMPORT_NAMESPACE') from error
        require(isinstance(source.get('pair'), list) and len(source['pair']) == 2, 'RELATIONSHIP_IMPORT_PAIR')
        for item in source['pair']: domain(item)


def document(value):
    require(isinstance(value, dict) and value.get('schema') == 1, 'RELATIONSHIP_SCHEMA')
    try: UUID(value['namespace'])
    except (KeyError, ValueError, TypeError, AttributeError) as error: raise ValueError('RELATIONSHIP_NAMESPACE') from error
    require(type(value.get('revision')) is int and value['revision'] >= 0, 'RELATIONSHIP_REVISION')
    require(isinstance(value.get('manifest'), dict) and isinstance(value.get('records'), dict), 'RELATIONSHIP_DOCUMENT')
    require(len(value['records']) <= 1000000, 'RELATIONSHIP_RESOURCE_LIMIT')
    manifest(value['manifest'])
    token(value)
    for identity, row in value['records'].items(): record(row, identity, value['namespace'])
    return value


def manifest(value):
    if not value: return
    require(isinstance(value.get('version'), str) and isinstance(value.get('settings'), dict)
        and isinstance(value.get('domains'), dict), 'RELATIONSHIP_MANIFEST')
    require(all(type(value['settings'].get(k)) in (int, float) and value['settings'][k] >= 0 for k in ('min_projected_area', 'epsilon')), 'RELATIONSHIP_MANIFEST_SETTINGS')
    import json
    for key, stamp in value['domains'].items():
        try: domain(json.loads(key))
        except (ValueError, TypeError) as error: raise ValueError('RELATIONSHIP_MANIFEST_DOMAIN') from error
        require(isinstance(stamp, dict) and all(isinstance(stamp.get(k), str) for k in
            ('topology', 'order', 'own', 'material', 'obstacles')), 'RELATIONSHIP_MANIFEST_STAMP')
        require(type(stamp.get('allowance')) in (int, float) and stamp['allowance'] >= 0, 'RELATIONSHIP_MANIFEST_ALLOWANCE')
