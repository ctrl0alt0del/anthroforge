"""Conservative reference inventory and validated removal of disposable backups."""
import gzip
import json
import os
import re
import struct
from pathlib import Path
from storage_support import safe, fingerprint, save, current, run_items, progress


def references(root, run, rows):
    names = {Path(r['path']).name for r in rows if r['path'].endswith('.blend1')}
    cold = json.loads((run / 'bootstrap.json').read_text())['cold_runs']
    result = dict(backup_names=set(), run_names=set())
    candidates = [root / r['path'] for r in rows if eligible_metadata(r)]
    repo = Path(__file__).resolve().parents[2]
    skill = Path.home() / '.codex/skills/anthroforge-muscle-reconstruction'
    for base in (repo / 'docs', repo / 'tests', repo / 'tools', skill):
        candidates.extend(p for p in base.rglob('*') if p.suffix in ('.py', '.md', '.json') and p.is_file())
    for p in candidates:
        text = p.read_text(encoding='utf-8', errors='replace')
        if '.blend1' in text: result['backup_names'].update(n for n in names if n in text)
        result['run_names'].update(n for n in cold if n in text and n not in str(p))
    return {k: sorted(v) for k, v in result.items()}


def eligible_metadata(row):
    path = Path(row['path'])
    return (path.suffix in ('.json', '.md', '.py')
            and not row['path'].startswith(('maintenance/', 'runtime/')))


def blend_stream(path):
    import zstandard
    with path.open('rb') as source:
        header = source.read(4); source.seek(0)
        if header == bytes.fromhex('28b52ffd'):
            with zstandard.ZstdDecompressor().stream_reader(source) as stream:
                return blend_blocks(stream)
        if header[:2] == b'\x1f\x8b':
            with gzip.GzipFile(fileobj=source) as stream:
                return blend_blocks(stream)
        return blend_blocks(source)


def blend_blocks(stream):
    size, offset, format = blend_header(stream)
    count, codes = 0, set()
    while True:
        block = stream.read(size)
        if len(block) != size: raise ValueError('Truncated Blender block header')
        length = struct.unpack_from(format, block, offset)[0]
        if length < 0: raise ValueError('Negative Blender payload')
        drain(stream, length); count += 1; codes.add(block[:4])
        if block[:4] == b'ENDB':
            if length or stream.read(1): raise ValueError('Invalid Blender end block')
            if not {b'GLOB', b'DNA1'} <= codes: raise ValueError('Missing Blender structures')
            return count


def blend_header(stream):
    header = stream.read(12)
    if re.fullmatch(rb'BLENDER[-_][vV][0-9]{3}', header):
        return (24 if header[7:8] == b'-' else 20), 4, ('<' if header[8:9] == b'v' else '>') + 'i'
    header += stream.read(5)
    if re.fullmatch(rb'BLENDER17-01v[0-9]{4}', header):
        return 32, 16, '<q'
    raise ValueError('Invalid or unsupported Blender header')


def drain(stream, length):
    while length:
        chunk = stream.read(min(length, 1024 * 1024))
        if not chunk: raise ValueError('Truncated Blender payload')
        length -= len(chunk)


def plan_backup(root, row, live, references):
    path, primary = safe(root, row['path']), safe(root, row['path'][:-1])
    if row['path'][:-1] in live or path.name in references['backup_names']:
        return dict(path=row['path'], action='keep', reason='current recovery point or referenced backup')
    try:
        backup, newer = fingerprint(path), fingerprint(primary)
        if newer['mtime_ns'] < backup['mtime_ns']:
            raise ValueError('Primary is older than its backup')
        blocks = blend_stream(primary)
        return dict(path=row['path'], action='remove', primary=row['path'][:-1],
                    backup=backup, newer=newer, validated_blocks=blocks)
    except Exception as error:
        return dict(path=row['path'], action='keep', reason=str(error))


def backup_plan(root, run, rows):
    refs = references(root, run, rows); save(run / 'reference_protection.json', refs)
    catalogue, live = current(root)
    backups = [r for r in rows if r['path'].endswith('.blend1')]
    result = [plan_backup(root, r, live, refs) for r in backups]
    return save(run / 'backup_plan.json', dict(catalogue_revision=catalogue['revision'], entries=result))


def remove_backups(root, run):
    plan = json.loads((run / 'backup_plan.json').read_text())
    checked = {r['path']: r for r in json.loads((run / 'backup_blender_load.json').read_text())}
    if current(root)[0]['revision'] != plan['catalogue_revision']:
        raise ValueError('Catalogue changed; rebuild retention plan')
    results = []
    for entry in plan['entries']:
        if entry['action'] != 'remove': continue
        proof = checked.get(entry['primary'], {})
        if proof.get('status') != 'loaded' or proof.get('sha256') != entry['newer']['sha256']:
            raise ValueError('Primary has not passed Blender loading: ' + entry['primary'])
        results.append(remove_backup(root, entry))
        save(run / 'backup_removal.json', results)
        progress('backups', len(results), len(plan['entries']))
    return results


def remove_backup(root, entry):
    path = safe(root, entry['path']); primary = safe(root, entry['primary'])
    if not path.exists(): return dict(path=entry['path'], status='already_removed')
    if fingerprint(path) != entry['backup'] or fingerprint(primary) != entry['newer']:
        raise ValueError('Backup or primary changed since planning')
    from core.authoring.storage_windows import compressed_size
    saved = compressed_size(path)
    path.unlink()
    return dict(path=entry['path'], status='removed', saved_bytes=saved, sha256=entry['backup']['sha256'])
