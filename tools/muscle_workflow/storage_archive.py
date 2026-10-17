"""Verified ZIP cold storage with manifests and non-overwriting restoration."""
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from storage_support import current, fingerprint, safe, save


def create_archives(root, run):
    cold = json.loads((run / 'bootstrap.json').read_text())['cold_runs']
    refs = json.loads((run / 'reference_protection.json').read_text())['run_names']
    live = current(root)[1]
    selected = [n for n in cold if n not in refs and not any(p == 'runs/' + n or p.startswith('runs/' + n + '/') for p in live)]
    manifests = [create_archive(root, 'runs/' + name) for name in selected]
    return save(run / 'archives.json', manifests)


def create_archive(root, relative):
    folder = run_folder(root, relative)
    files = sorted(safe(root, p.relative_to(root)) for p in folder.rglob('*') if p.is_file())
    entries = [dict(path=p.relative_to(root).as_posix(), **fingerprint(p)) for p in files]
    archive = safe(root, 'storage/archives/' + folder.name + '.zip')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for entry in entries: output.write(safe(root, entry['path']), entry['path'])
    manifest = dict(schema_version=1, source=relative, entries=entries,
                    archive=archive.relative_to(root).as_posix(), digest=fingerprint(archive))
    verify_archive(root, manifest)
    destination = archive.with_suffix('.manifest.json')
    save(destination, manifest)
    return destination.relative_to(root).as_posix()


def run_folder(root, relative):
    folder = safe(root, relative).resolve()
    if folder.parent != (root / 'runs').resolve() or folder.relative_to(root).as_posix() != relative:
        raise ValueError('Only canonical historical run directories can be archived or retired')
    return folder


def verify_archive(root, manifest):
    archive = safe(root, manifest['archive'])
    if fingerprint(archive)['sha256'] != manifest['digest']['sha256']:
        raise ValueError('Archive checksum mismatch')
    expected = {entry['path']: entry for entry in manifest['entries']}
    with zipfile.ZipFile(archive) as source:
        if len(source.namelist()) != len(expected) or set(source.namelist()) != set(expected):
            raise ValueError('Archive member mismatch')
        for name, entry in expected.items():
            safe(root, name)
            with source.open(name) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != entry['sha256'] or source.getinfo(name).file_size != entry['bytes']:
                raise ValueError('Archive member checksum mismatch: ' + name)


def retire_archives(root, run):
    results = []
    for relative in json.loads((run / 'archives.json').read_text()):
        manifest = json.loads(safe(root, relative).read_text())
        verify_archive(root, manifest)
        assert_retirable(root, manifest)
        for entry in manifest['entries']:
            expected = {k: v for k, v in entry.items() if k != 'path'}
            if fingerprint(safe(root, entry['path'])) != expected:
                raise ValueError('History changed after archiving')
        results.append(retire_files(root, manifest, relative))
        save(run / 'archive_retirement.json', results)
    return results


def assert_retirable(root, manifest):
    run_folder(root, manifest['source'])
    live = current(root)[1]
    prefix = manifest['source'] + '/'
    if not prefix.startswith('runs/'):
        raise ValueError('Only historical runs can be retired')
    for entry in manifest['entries']:
        name = entry['path']
        if not name.startswith(prefix) or any(name == p or name.startswith(p + '/') for p in live):
            raise ValueError('Archive contains protected or unrelated paths')


def retire_files(root, manifest, relative):
    from core.authoring.storage_windows import compressed_size
    saved = 0
    for entry in manifest['entries']:
        path = safe(root, entry['path'])
        if fingerprint(path)['sha256'] != entry['sha256']:
            raise ValueError('History changed before removal')
        saved += compressed_size(path); path.unlink()
    marker = safe(root, manifest['source'] + '/ARCHIVED.json')
    save(marker, dict(manifest=relative, restore='storage_maintenance.py archive-restore --manifest ' + relative))
    return dict(manifest=relative, removed_files=len(manifest['entries']), removed_bytes=saved)


def restore_archive(root, manifest_path, destination=None):
    manifest = json.loads(safe(root, manifest_path).read_text())
    verify_archive(root, manifest)
    destination = root if destination is None else destination.resolve(strict=True)
    for entry in manifest['entries']:
        path = safe(destination, entry['path'])
        if path.exists() and fingerprint(path)['sha256'] != entry['sha256']:
            raise ValueError('Refusing to overwrite existing different file: ' + str(path))
    with zipfile.ZipFile(safe(root, manifest['archive'])) as source:
        for entry in manifest['entries']:
            restore_file(source, safe(destination, entry['path']), entry)
    return dict(restored_files=len(manifest['entries']), destination=str(destination))


def restore_file(source, path, entry):
    if path.exists(): return
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.restore-')
    try:
        with os.fdopen(handle, 'wb') as output, source.open(entry['path']) as data:
            shutil.copyfileobj(data, output); output.flush(); os.fsync(output.fileno())
        if fingerprint(Path(temporary))['sha256'] != entry['sha256']:
            raise ValueError('Restored checksum mismatch')
        os.link(temporary, path)
        os.utime(path, ns=(entry['mtime_ns'], entry['mtime_ns']))
    finally:
        Path(temporary).unlink(missing_ok=True)
