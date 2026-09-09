"""Exact portable references and dependency traversal."""
from .errors import require, AuthoringError
from .codec import digest


def tokens(ref):
    require(isinstance(ref, str) and ref.startswith('/'), 'INVALID_REFERENCE', str(ref))
    require(all('~' not in p.replace('~0', '').replace('~1', '') for p in ref[1:].split('/')), 'INVALID_REFERENCE')
    return [p.replace('~1', '/').replace('~0', '~') for p in ref[1:].split('/')]


def lookup(document, ref):
    value = document
    for key in tokens(ref):
        if isinstance(value, list):
            require(key.isdigit() and str(int(key)) == key and int(key) < len(value), 'REFERENCE_UNDEFINED', ref, ref)
            value = value[int(key)]
            continue
        require(isinstance(value, dict) and key in value, 'REFERENCE_UNDEFINED', ref, ref)
        value = value[key]
    return value


def references(value):
    if isinstance(value, dict):
        return set().union(*(references(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(references(v) for v in value)) if value else set()
    return {value} if isinstance(value, str) and value.startswith('/') else set()


def graph(document):
    result = {}
    for group, rows in document.items():
        if isinstance(rows, dict):
            for key, value in rows.items():
                result['/'+group+'/'+key] = references(value)
    for profile, value in document.get('skeleton_profiles', {}).items():
        for group in ('bindings', 'frames', 'controls', 'landmarks', 'regions', 'measurements'):
            for key, row in value.get(group, {}).items():
                result['/skeleton_profiles/'+profile+'/'+group+'/'+key] = references(row)
    return result


def closure(edges, roots):
    result, pending = set(roots), list(roots)
    while pending:
        key = pending.pop()
        for child in edges.get(key, ()):
            if child not in result:
                result.add(child)
                pending.append(child)
    return result


def affected(document, changed):
    edges = graph(document)
    seeds = {k for k in edges if any(within(k, p) or within(p, k) for p in changed)}
    reverse = {k: {n for n, deps in edges.items() if any(within(d, k) for d in deps)} for k in edges}
    return sorted(closure(reverse, seeds))


def within(child, parent):
    return child == parent or child.startswith(parent+'/')


def fingerprint(document, ref, active=()):
    require(ref not in active, 'REQUIREMENT_CYCLE', ' -> '.join((*active, ref)))
    value = lookup(document, ref)
    deps = {r: fingerprint(document, r, (*active, ref)) for r in sorted(references(value))}
    return digest([value, deps])
