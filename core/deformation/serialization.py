"""Bounded, checksummed NPZ payload suitable for a packed Blender Text block."""
import base64
import io
import json
import zipfile
import numpy as np
from .reference import DeformationReference, canonical

MAX_BYTES = 512 * 1024 * 1024


def encode(reference):
    stream = io.BytesIO()
    metadata = dict(reference.metadata, content_signature=reference.signature)
    np.savez_compressed(stream, _metadata=np.frombuffer(canonical(metadata), np.uint8), **reference.arrays)
    if stream.tell() > MAX_BYTES:
        raise ValueError("Deformation reference exceeds the storage budget.")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def decode(text):
    if len(text) > (MAX_BYTES * 4 // 3 + 4):
        raise ValueError("Deformation reference exceeds the storage budget.")
    payload = base64.b64decode(text, validate=True)
    check_archive(payload)
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        metadata = json.loads(archive["_metadata"].tobytes())
        signature = metadata.pop("content_signature")
        reference = DeformationReference({k: archive[k] for k in archive.files if k != "_metadata"}, metadata)
    if reference.signature != signature:
        raise ValueError("Deformation reference checksum mismatch.")
    return reference


def check_archive(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 4096:
            raise ValueError("Invalid deformation reference archive entries.")
        if sum(item.file_size for item in archive.infolist()) > MAX_BYTES:
            raise ValueError("Expanded deformation reference exceeds the storage budget.")
