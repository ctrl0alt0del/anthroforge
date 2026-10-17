"""Byte-preserving compression and verified immutable-asset deduplication."""
import os
import re
from pathlib import Path
from core.authoring.storage_pool import link
from core.authoring.storage_windows import compress, compressed_size
from storage_support import safe, fingerprint, run_items, save, protected_rows


def baseline(root, run, rows):
    revision, selected = protected_rows(root, rows)
    result = run_items('protect', selected, lambda row: inspect(root, row), run / 'protected.jsonl.gz')
    result.update(catalogue_revision=revision, protected_files=len(selected))
    save(run / 'protection.json', result)
    if result['failures']:
        raise ValueError('Cannot protect every current artifact')
    return result


def inspect(root, row):
    try:
        return dict(path=row['path'], status='verified', **fingerprint(safe(root, row['path'])))
    except Exception as error:
        return dict(path=row['path'], status='error', error=str(error))


def compression(root, run, rows):
    extensions = {'.json', '.jsonl', '.svg', '.txt', '.log', '.dot', '.csv', '.py'}
    selected = [r for r in rows if Path(r['path']).suffix in extensions and r['bytes'] >= 4096
                and not r['path'].startswith(('runtime/', 'maintenance/'))]
    result = run_items('compress', unique_files(root, selected), lambda row: compress_file(root, row),
                       run / 'compression.jsonl.gz', workers=2)
    return save(run / 'compression_result.json', result)


def unique_files(root, rows):
    seen, result = set(), []
    for row in rows:
        info = safe(root, row['path']).stat()
        identity = (info.st_dev, info.st_ino)
        if identity not in seen:
            result.append(row); seen.add(identity)
    return result


def compress_file(root, row):
    try:
        path = safe(root, row['path'])
        compressed = bool(path.stat().st_file_attributes & 0x800)
        if compressed and compressed_size(path) < path.stat().st_size:
            return dict(path=row['path'], status='already_compressed')
        before, allocated = fingerprint(path), compressed_size(path)
        compress(path, force=compressed)
        after = fingerprint(path)
        if before['sha256'] != after['sha256']:
            raise ValueError('Content changed during compression')
        return dict(path=row['path'], status='compressed', saved_bytes=allocated-compressed_size(path), **after)
    except Exception as error:
        return dict(path=row['path'], status='error', error=str(error))


def assets(root, run, rows):
    selected = [r for r in rows if Path(r['path']).parent.name.endswith('.authoring')
                and Path(r['path']).suffix in ('.json', '.svg')
                and re.fullmatch('[a-f0-9]{64}', Path(r['path']).stem)]
    result = run_items('assets', selected, lambda row: share_asset(root, row), run / 'assets.jsonl.gz', workers=1)
    return save(run / 'assets_result.json', result)


def share_asset(root, row):
    try:
        path = safe(root, row['path']); before = fingerprint(path)
        if before['sha256'] != path.stem:
            return dict(path=row['path'], status='mutable_or_noncanonical')
        pool = safe(root, 'storage/immutable-assets/' + path.stem[:2] + '/' + path.name)
        pool.parent.mkdir(parents=True, exist_ok=True)
        return share_verified(path, pool, row['path'], before)
    except Exception as error:
        return dict(path=row['path'], status='error', error=str(error))


def share_verified(path, pool, relative, before):
    if not pool.exists():
        os.link(path, pool)
        return dict(path=relative, status='canonical', **before)
    if fingerprint(pool)['sha256'] != before['sha256']:
        raise ValueError('Immutable pool content changed')
    allocated, links = compressed_size(path), path.stat().st_nlink
    changed = link(pool, path, before['sha256'])
    return dict(path=relative, status='shared' if changed else 'already_shared',
                saved_bytes=allocated if changed and links == 1 else 0, **before)


def verify_protected(root, run):
    from storage_support import gzip_rows
    rows = list(gzip_rows(run / 'protected.jsonl.gz'))
    result = run_items('verify', rows, lambda row: compare(root, row), run / 'verified.jsonl.gz')
    return save(run / 'verification.json', result)


def compare(root, row):
    actual = inspect(root, row)
    if actual.get('sha256') != row['sha256']:
        actual.update(status='error', error='Protected content changed')
    return actual
