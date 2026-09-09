"""Verified checkpoint generations; completion is written last."""
from pathlib import Path
import hashlib
import shutil
import os
import tempfile
from ...core.authoring.codec import digest, encode
from ...core.authoring.errors import require
from ...core.authoring.storage import atomic_write


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checkpoint(service, request):
    record = service.load(request['params'])
    service.check(request['params'], record)
    identity = digest([service.inventory['root_id'], request])
    saved = service.store.get('v04_generations', identity)
    if saved and saved.get('complete'):
        verify(saved)
        return dict(generation=saved, replayed=True)
    folder = generation_folder(service, identity)
    manifest = prepare(service, record, identity, folder)
    service.checkpoints.save_checkpoint(folder / 'scene.blend', dict(generation_id=identity, draft_sha256=manifest['draft']['sha256']))
    manifest['scene'] = dict(path=str(folder / 'scene.blend'), sha256=file_digest(folder / 'scene.blend'))
    manifest['complete'] = True
    service.store.put('v04_generations', identity, manifest)
    return dict(generation=manifest, assets=[manifest['draft'], manifest['scene']])


def generation_folder(service, identity):
    folder = service.store.directory / 'generations' / identity
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def prepare(service, record, identity, folder):
    records = service.repository.all()
    document = snapshot_assets(folder, [service.store.asset(record, 'draft_generation')])[0]
    documents = snapshot_assets(folder, [service.store.asset(r, 'draft_generation') for r in records])
    assets, packages, candidates = scene_assets(service, records, folder)
    manifest = dict(id=identity, root_id=service.inventory['root_id'], complete=False, draft=document, documents=documents, assets=assets, packages=packages, candidates=candidates, scene_revision=service.inventory['revision'])
    service.store.put('v04_generations', identity, manifest)
    return manifest


def scene_assets(service, records, folder):
    assets, packages, candidates = [], [], []
    for record in records:
        assets.extend(record.get('compiled', {}).get('assets', []))
        collect_packages(record['document'], service.store.directory/'packages', packages)
        for adoption in record.get('adoptions', []):
            key = [record['document']['document_id'], adoption['candidate']]
            candidate = service.store.get('v04_candidates', key)
            require(candidate is not None, 'CHECKPOINT_PROVENANCE_MISSING')
            assets.extend(candidate['previews'])
            asset = snapshot_assets(folder, [service.store.asset(candidate, 'candidate')])[0]
            candidates.append(dict(key=key, asset=asset))
    return snapshot_assets(folder, assets), snapshot_assets(folder, packages), candidates


def collect_packages(document, base, rows, active=(), package_root=None):
    from ...core.authoring.packages import load_package
    require(document['document_id'] not in active, 'PACKAGE_CYCLE')
    for entry in document.get('imports', {}).values():
        package, parent = load_package(entry, base)
        source = (Path(base)/entry['path']).resolve()
        rows.append(dict(path=str(source), sha256=entry['sha256'], logical_path=str(source.relative_to(Path(package_root or base).resolve()))))
        collect_packages(package, parent, rows, active+(document['document_id'],), package_root or base)


def snapshot_assets(folder, assets):
    result = []
    for asset in assets:
        source = Path(asset['path'])
        target = folder/(asset['sha256']+source.suffix)
        require(file_digest(source) == asset['sha256'], 'CHECKPOINT_ASSET_CHANGED')
        atomic_write(target, source.read_bytes())
        result.append(dict(asset, path=str(target)))
    return result


def verify(manifest):
    require(manifest and manifest.get('complete'), 'CHECKPOINT_INCOMPLETE')
    for asset in [manifest['draft'], manifest['scene']]+manifest['assets']+manifest['packages']+manifest.get('documents', []):
        require(Path(asset['path']).is_file(), 'CHECKPOINT_ASSET_MISSING')
        require(file_digest(asset['path']) == asset['sha256'], 'CHECKPOINT_DIGEST_MISMATCH')
    for row in manifest.get('candidates', []):
        require(file_digest(row['asset']['path']) == row['asset']['sha256'], 'CHECKPOINT_DIGEST_MISMATCH')


def recover(service, request):
    params = request['params']
    manifest = service.store.get('v04_generations', params['generation_id'])
    verify(manifest)
    target = Path(params['output_path']).resolve()
    reused = recovery_preflight(target, manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not reused:
        recover_generation(target, manifest)
    return dict(recovered_copy=str(target), generation_id=manifest['id'], draft=manifest['draft'], restored_active_scene=False, replayed=reused)


def recovery_preflight(target, manifest):
    from ...core.authoring.storage import FileStore
    folder = target.with_suffix('.authoring')
    marker = FileStore(folder).get('v04_recovery', 'generation') if folder.exists() else None
    compatible = marker == dict(id=manifest['id'], scene_sha256=manifest['scene']['sha256'])
    require(target.suffix == '.blend', 'RECOVERY_REQUIRES_NEW_COPY')
    require(not folder.exists() or compatible, 'RECOVERY_JOURNAL_EXISTS')
    require(not target.exists() or compatible and file_digest(target) == manifest['scene']['sha256'], 'RECOVERY_REQUIRES_NEW_COPY')
    return target.exists()


def recover_generation(target, manifest):
    with tempfile.TemporaryDirectory(prefix='.af_recovery_', dir=target.parent) as temporary:
        staged = Path(temporary)/target.name
        shutil.copyfile(manifest['scene']['path'], staged)
        require(file_digest(staged) == manifest['scene']['sha256'], 'RECOVERY_DIGEST_MISMATCH')
        if not target.with_suffix('.authoring').exists():
            restore_journal(staged, manifest, target.with_suffix('.authoring'))
            staged.with_suffix('.authoring').rename(target.with_suffix('.authoring'))
        os.rename(staged, target)


def restore_journal(target, manifest, final_folder=None):
    from ...core.authoring.storage import FileStore
    folder = target.with_suffix('.authoring')
    require(not folder.exists(), 'RECOVERY_JOURNAL_EXISTS')
    store = FileStore(folder)
    assets = restore_assets(store, manifest)
    assets = {k: str((final_folder or folder)/Path(v).name) for k, v in assets.items()}
    restore_documents(store, manifest, assets)
    restore_candidates(store, manifest, assets)
    restore_packages(folder, manifest)
    store.put('v04_recovery', 'generation', dict(id=manifest['id'], scene_sha256=manifest['scene']['sha256']))


def restore_packages(folder, manifest):
    for package in manifest['packages']:
        destination = (folder/'packages'/package['logical_path']).resolve()
        require(destination.is_relative_to((folder/'packages').resolve()), 'PACKAGE_PATH_ESCAPE')
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(destination, Path(package['path']).read_bytes())


def restore_documents(store, manifest, assets):
    from ...core.authoring.codec import decode
    for asset in manifest.get('documents', [manifest['draft']]):
        record = decode(Path(asset['path']).read_text(), 256_000_000)
        store.put('v04_drafts', [manifest['root_id'], record['document']['document_id']], relocate(record, assets))


def restore_candidates(store, manifest, assets):
    from ...core.authoring.codec import decode
    for row in manifest.get('candidates', []):
        value = decode(Path(row['asset']['path']).read_text(), 256_000_000)
        store.put('v04_candidates', row['key'], relocate(value, assets))


def restore_assets(store, manifest):
    result = {}
    for asset in manifest['assets']:
        target = store.directory/(asset['sha256']+Path(asset['path']).suffix)
        atomic_write(target, Path(asset['path']).read_bytes())
        result[asset['sha256']] = str(target)
    return result


def relocate(value, assets):
    if isinstance(value, list):
        return [relocate(v, assets) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: relocate(v, assets) for k, v in value.items()}
    if result.get('sha256') in assets and 'path' in result:
        result['path'] = assets[result['sha256']]
    return result
