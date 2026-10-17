"""Fast directory inventory and hard-link-aware stored-data accounting."""
import os
from pathlib import Path


def walk_files(root):
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if getattr(info, 'st_file_attributes', 0) & 0x400 or entry.is_symlink():
                    raise ValueError('Inventory contains a reparse point: ' + entry.path)
                if entry.is_dir(follow_symlinks=False): pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False): yield Path(entry.path), info


def collect(root):
    return [dict(path=p.relative_to(root).as_posix(), bytes=s.st_size, mtime_ns=s.st_mtime_ns)
            for p, s in walk_files(root)]


def measure(root):
    from core.authoring.storage_windows import compressed_size
    seen, logical, stored, files = set(), 0, 0, 0
    for path, info in walk_files(root):
        logical += info.st_size; files += 1
        identity_stat = path.stat()
        identity = (identity_stat.st_dev, identity_stat.st_ino)
        if identity not in seen:
            stored += compressed_size(path); seen.add(identity)
    return dict(files=files, unique_files=len(seen), logical_bytes=logical, stored_data_bytes=stored,
                note='Unique file data using GetCompressedFileSizeW; excludes filesystem metadata and cluster slack.')
