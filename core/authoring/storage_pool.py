"""Opt-in shared immutable assets, with portable ordinary-file journal aliases."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def policy(directory):
    for root in (directory, *directory.parents):
        marker = root / '.authoring-storage.json'
        if not marker.is_file():
            continue
        value = json.loads(marker.read_text(encoding='utf-8'))
        if value.get('schema_version') != 1:
            raise ValueError('Unsupported authoring storage policy')
        pool = (root / value['immutable_asset_pool']).resolve()
        if not pool.is_relative_to(root.resolve()) or pool == root.resolve():
            raise ValueError('Asset pool must stay inside its policy root')
        return dict(value, pool=pool)
    return None


def prepare(directory, settings):
    if settings and settings.get('compress_journals'):
        from .storage_windows import compress
        compress(directory)


def verify(path, identity):
    with path.open('rb') as stream:
        actual = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            actual.update(chunk)
    if actual.hexdigest() != identity:
        raise ValueError('Immutable asset hash mismatch: ' + str(path))


def blob(pool, identity, suffix, content, settings=None):
    from .storage import atomic_write
    path = pool / identity[:2] / (identity + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    prepare(path.parent, settings)
    if path.exists():
        verify(path, identity)
    else:
        atomic_write(path, content)
    return path


def link(source, destination, identity):
    if destination.exists():
        if source.samefile(destination):
            return False
        verify(destination, identity)
    temporary = destination.with_name('.asset-link-' + uuid4().hex)
    try:
        os.link(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def publish(directory, content, suffix, settings):
    from .storage import atomic_write
    identity = hashlib.sha256(content).hexdigest()
    destination = directory / (identity + suffix)
    if settings:
        source = blob(settings['pool'], identity, suffix, content, settings)
        portable_link(source, destination, identity, content)
    elif destination.exists():
        verify(destination, identity)
    else:
        atomic_write(destination, content)
    return identity, destination


def portable_link(source, destination, identity, content):
    from .storage import atomic_write
    try:
        link(source, destination, identity)
    except OSError:
        atomic_write(destination, content)
