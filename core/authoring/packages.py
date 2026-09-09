"""Offline locked package expansion; imports never execute code."""
from pathlib import Path
from copy import deepcopy
import hashlib
from .codec import decode
from .errors import require


def load_package(entry, base):
    path = (Path(base)/entry['path']).resolve()
    require(path.is_relative_to(Path(base).resolve()), 'PACKAGE_PATH_ESCAPE')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == entry['sha256'], 'PACKAGE_HASH_MISMATCH')
    data = decode(raw.decode('utf-8'))
    require(data['document_id'] == entry['document_id'] and data['version'] == entry['version'], 'PACKAGE_ID_MISMATCH')
    from .validation import document
    document(data)
    return data, path.parent


def rewrite(value, prefix):
    if isinstance(value, dict):
        return {k: source_refs(v, prefix) if k == 'sources' and isinstance(v, list) else rewrite(v, prefix) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, prefix) for v in value]
    if isinstance(value, str) and value.startswith('/'):
        parts = value.split('/')
        if len(parts) > 2:
            parts[2] = prefix+parts[2]
        return '/'.join(parts)
    return value


def source_refs(values, prefix):
    return [rewrite(v, prefix) if v.startswith('/') or '#/' in v else prefix+v for v in values]


def imported_refs(value):
    if isinstance(value, dict):
        return {k: imported_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [imported_refs(v) for v in value]
    if isinstance(value, str) and '#/' in value:
        alias, ref = value.split('#', 1)
        return rewrite(ref, alias+'__')
    return value


def expand(document, base, active=()):
    identity = document['document_id']
    require(identity not in active, 'PACKAGE_CYCLE', identity)
    result = deepcopy(document)
    for alias, entry in document.get('imports', {}).items():
        package, folder = load_package(entry, base)
        merge(result, expand(package, folder, (*active, identity)), alias)
    result['imports'] = {}
    return imported_refs(result)


def merge(target, package, alias):
    metadata = {'$schema', 'dsl', 'version', 'document_id', 'revision', 'kind', 'requires', 'imports', 'project', 'limits'}
    target['requires'] = sorted(set(target.get('requires', [])) | set(package.get('requires', [])))
    for group, rows in package.items():
        if group in metadata:
            continue
        require(isinstance(rows, dict), 'INVALID_PACKAGE_COLLECTION', group)
        for key, value in rows.items():
            name = alias+'__'+key
            require(name not in target.setdefault(group, {}), 'PACKAGE_COLLISION', name)
            target[group][name] = rewrite(value, alias+'__')
