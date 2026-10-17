"""Bounded paths and durable receipts for opt-in workflow storage maintenance."""
import gzip
import hashlib
import json
import os
import time
from pathlib import Path


def safe(root, relative):
    root = Path(root).resolve(strict=True)
    target = root / relative
    resolved = target.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError('Path escapes maintenance root: ' + str(target))
    for item in (target, *target.parents):
        if item == root:
            break
        if item.is_symlink() or (item.exists() and item.stat().st_file_attributes & 0x400):
            raise ValueError('Reparse point is not a maintenance target: ' + str(item))
    return target


def fingerprint(path):
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('File changed while reading: ' + str(path))
    return dict(sha256=digest, bytes=after.st_size, mtime_ns=after.st_mtime_ns)


def save(path, value):
    from common import write_json
    return write_json(path, value)


def log(stream, value):
    stream.write(json.dumps(value, separators=(',', ':')) + '\n')


def progress(phase, index, total, **extra):
    print(json.dumps(dict(phase=phase, processed=index, total=total, **extra)), flush=True)


def inventory(root, run):
    import zstandard
    from storage_inventory import collect
    path = run / 'inventory.json.zst'
    if path.exists():
        return json.loads(zstandard.ZstdDecompressor().decompress(path.read_bytes()))
    rows = collect(root)
    from core.authoring.storage import atomic_write
    atomic_write(path, zstandard.ZstdCompressor(level=6).compress(json.dumps(rows).encode()))
    return rows


def current(root):
    root = Path(root).resolve(strict=True)
    data = json.loads((root / 'catalogue/catalogue.json').read_text())
    paths = set()
    for family in data['families']:
        build = family.get('current_build') or {}
        for key in ('blend', 'journal'):
            value = build.get(key) or {}
            path = value.get('path') if isinstance(value, dict) else value
            if path:
                resolved = (root / path).resolve()
                if resolved.is_relative_to(root): paths.add(resolved.relative_to(root).as_posix())
    return data, paths


def protected_rows(root, rows):
    data, paths = current(root)
    prefixes = tuple(p + '/' for p in paths)
    selected = [r for r in rows if r['path'] in paths or r['path'].startswith(prefixes)
                or r['path'].startswith(('catalogue/', 'knowledge/', 'assets/'))]
    return data['revision'], selected


def gzip_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def run_items(phase, rows, action, receipt, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    counts, totals, failures, last = {}, {}, [], time.monotonic()
    with gzip.open(receipt, 'wt', encoding='utf-8') as stream, ThreadPoolExecutor(workers) as executor:
        for index, result in enumerate(executor.map(action, rows), 1):
            log(stream, result)
            status = result.get('status', 'verified'); counts[status] = counts.get(status, 0) + 1
            if status == 'error': failures.append(result)
            for key in ('saved_bytes', 'bytes'): totals[key] = totals.get(key, 0) + result.get(key, 0)
            if time.monotonic() - last > 20:
                progress(phase, index, len(rows), counts=counts, totals=totals); last = time.monotonic()
    return dict(counts=counts, totals=totals, failures=failures)
