"""Atomic JSON journal and content-addressed assets."""
import os
import tempfile
from pathlib import Path
from .codec import decode, encode, digest


class FileStore:
    def __init__(self, directory):
        from .storage_pool import policy, prepare
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.storage_policy = policy(self.directory.resolve())
        prepare(self.directory, self.storage_policy)

    def path(self, category, key):
        from .storage_pool import prepare
        folder = self.directory / category
        folder.mkdir(exist_ok=True)
        prepare(folder, self.storage_policy)
        return folder / (digest(key) + ".json")

    def get(self, category, key):
        path = self.path(category, key)
        return decode(path.read_text(encoding="utf-8"), 256_000_000) if path.exists() else None

    def put(self, category, key, value):
        atomic_write(self.path(category, key), encode(value).encode("utf-8"))

    def asset(self, value, kind="geometry"):
        from .storage_pool import publish
        content = encode(value).encode("utf-8")
        identity, path = publish(self.directory, content, '.json', self.storage_policy)
        return dict(id="asset_"+identity, kind=kind, path=str(path), sha256=identity)

    def image(self, content):
        from .storage_pool import publish
        raw = content.encode("utf-8")
        identity, path = publish(self.directory, raw, '.svg', self.storage_policy)
        return dict(id="asset_"+identity, kind="image", path=str(path), sha256=identity)


def atomic_write(path, content):
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending_")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
