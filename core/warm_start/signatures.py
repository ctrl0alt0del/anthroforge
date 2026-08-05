import hashlib
import json
from dataclasses import asdict, is_dataclass

import numpy as np


def structural_signature(vertex_count, faces):
    digest = hashlib.sha256(str(int(vertex_count)).encode())
    _array(digest, np.asarray(faces, dtype=np.int32))
    return digest.hexdigest()


def source_identity_signature(sources):
    values = [(item.source_index, item.entity_type, item.entity_id, item.mirror_role)
              for item in sources]
    return _json_hash(values)


def source_connectivity_signature(sources):
    digest = hashlib.sha256(source_identity_signature(sources).encode())
    for source in sources:
        _array(digest, np.asarray(source.triangles, dtype=np.int32))
    return digest.hexdigest()


def geometry_state_hash(sources):
    digest = hashlib.sha256()
    for source in sources:
        _array(digest, np.asarray(source.vertices, dtype=np.float64))
    return digest.hexdigest()


def solver_settings_hash(settings):
    payload = asdict(settings) if is_dataclass(settings) else settings
    return _json_hash(payload)


def guide_layout_signature(guides):
    digest = hashlib.sha256()
    for guide in guides:
        identity = (guide.guide_index, guide.fiber_id, guide.mirror_role, len(guide.points))
        digest.update(str(identity).encode())
    return digest.hexdigest()


def mesh_geometry_hash(vertices):
    digest = hashlib.sha256()
    _array(digest, np.asarray(vertices, dtype=np.float64))
    return digest.hexdigest()


def _json_hash(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _array(digest, value):
    array = np.ascontiguousarray(value)
    digest.update(str((array.shape, array.dtype.str)).encode())
    digest.update(array.view(np.uint8))
