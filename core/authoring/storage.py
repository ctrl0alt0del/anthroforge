"""Atomic JSON journal and content-addressed assets."""
import hashlib
import os
import tempfile
from pathlib import Path
from .codec import decode, encode, digest


class FileStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, category, key):
        folder = self.directory / category
        folder.mkdir(exist_ok=True)
        return folder / (digest(key) + ".json")

    def get(self, category, key):
        path = self.path(category, key)
        return decode(path.read_text(encoding="utf-8"), 256_000_000) if path.exists() else None

    def put(self, category, key, value):
        atomic_write(self.path(category, key), encode(value).encode("utf-8"))

    def asset(self, value, kind="geometry"):
        content = encode(value).encode("utf-8")
        identity = hashlib.sha256(content).hexdigest()
        path = self.directory / (identity + ".json")
        atomic_write(path, content)
        return dict(id="asset_"+identity, kind=kind, path=str(path), sha256=identity)

    def image(self, content):
        raw = content.encode("utf-8")
        identity = hashlib.sha256(raw).hexdigest()
        path = self.directory / (identity + ".svg")
        atomic_write(path, raw)
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
