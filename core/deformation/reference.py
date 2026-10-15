"""Versioned, immutable construction data; never contains executable objects."""
from dataclasses import dataclass, field
from types import MappingProxyType
import hashlib
import json
import numpy as np

SCHEMA = 1
CAPABILITY = "final_skin_le_fast_v1"
REQUIRED = {"vertices", "quads", "vertex_ids", "proxy_vertices", "proxy_tets",
            "samples", "sample_weights", "sample_owners", "sample_addresses"}


@dataclass(frozen=True)
class DeformationSettings:
    method: str = "LE"
    proxy_resolution: int = 48
    constraint_strength: float = 100.0
    fast_handles: int = 128


@dataclass(frozen=True)
class DeformationReference:
    arrays: object
    metadata: object = field(default_factory=dict)

    def __post_init__(self):
        arrays = {key: immutable(value) for key, value in self.arrays.items()}
        metadata = json.loads(canonical(self.metadata))
        validate(arrays, metadata)
        object.__setattr__(self, "arrays", MappingProxyType(arrays))
        object.__setattr__(self, "metadata", freeze(metadata))

    @property
    def signature(self):
        digest = hashlib.sha256(canonical(dict(self.metadata)))
        for key, value in sorted(self.arrays.items()):
            digest.update(canonical([key, value.dtype.str, list(value.shape)]))
            digest.update(value.tobytes())
        return digest.hexdigest()


def canonical(value):
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def plain(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def immutable(value):
    array = np.ascontiguousarray(value)
    if array.dtype.kind not in "biuf":
        raise ValueError("Deformation arrays must contain numeric data.")
    if not np.isfinite(array).all():
        raise ValueError("Deformation reference contains nonfinite data.")
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def validate(arrays, metadata):
    if REQUIRED - arrays.keys():
        raise ValueError("Incomplete deformation reference: " + str(sorted(REQUIRED-arrays.keys())))
    if metadata.get("schema") != SCHEMA or metadata.get("capability") != CAPABILITY:
        raise ValueError("Unsupported deformation reference version; explicitly reinitialize.")
    mesh(arrays["vertices"], arrays["quads"], 4)
    mesh(arrays["proxy_vertices"], arrays["proxy_tets"], 4)
    ids = arrays["vertex_ids"]
    if ids.dtype.kind not in "iu" or not np.array_equal(ids, np.arange(len(arrays["vertices"]))):
        raise ValueError("Invalid final-mesh vertex identities.")
    validate_samples(arrays, metadata)
    validate_embedding(arrays)
    validate_contact(arrays)


def validate_contact(arrays):
    if not {"symmetry_partners","symmetry_plane"}.intersection(arrays): return
    ids, plane = arrays.get("symmetry_partners"), arrays.get("symmetry_plane")
    count = len(arrays["vertices"])
    if ids is None or plane is None or ids.shape != (count,) or plane.shape != (6,):
        raise ValueError("Invalid contact reference arrays.")
    if ids.dtype.kind not in "iu" or np.any(ids < -1) or np.any(ids >= count):
        raise ValueError("Invalid symmetry correspondence addresses.")
    paired = np.flatnonzero(ids >= 0)
    if not np.array_equal(ids[ids[paired]],paired): raise ValueError("Nonreciprocal symmetry correspondence.")
    length = np.linalg.norm(plane[3:])
    if length != 0 and not np.isclose(length,1): raise ValueError("Invalid symmetry plane normal.")


def validate_embedding(arrays):
    keys = {"embedding_indices", "embedding_weights"}
    if not keys.intersection(arrays): return
    if not keys.issubset(arrays): raise ValueError("Incomplete final-mesh embedding.")
    indices, weights = arrays["embedding_indices"], arrays["embedding_weights"]
    shape = (len(arrays["vertices"]), 4)
    if indices.shape != shape or weights.shape != shape or indices.dtype.kind not in "iu":
        raise ValueError("Invalid final-mesh embedding arrays.")
    if indices.min() < 0 or indices.max() >= len(arrays["proxy_vertices"]):
        raise ValueError("Final-mesh embedding references unavailable proxy vertices.")
    if not np.allclose(weights.sum(axis=1), 1, atol=1e-8):
        raise ValueError("Final-mesh embedding weights do not sum to one.")


def mesh(vertices, faces, arity):
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
        raise ValueError("Invalid reference vertex array.")
    if faces.ndim != 2 or faces.shape[1] != arity or not len(faces):
        raise ValueError("Invalid reference connectivity.")
    if faces.dtype.kind not in "iu" or faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("Reference connectivity has invalid vertex addresses.")


def validate_samples(arrays, metadata):
    points = arrays["samples"]; count = len(points)
    if points.shape != (count, 3) or not count:
        raise ValueError("Reference requires anatomical samples.")
    for key in ("sample_weights", "sample_owners", "sample_addresses"):
        if arrays[key].shape != (count,):
            raise ValueError("Invalid sample array: " + key)
    for key in ("sample_owners", "sample_addresses"):
        if arrays[key].dtype.kind not in "iu" or arrays[key].min() < 0:
            raise ValueError("Invalid material address array: " + key)
    if arrays["sample_weights"].min() <= 0 or not np.isclose(arrays["sample_weights"].sum(), 1):
        raise ValueError("Sample weights must be positive and normalized.")
    contributors = metadata.get("contributors", ())
    if arrays["sample_owners"].max() >= len(contributors):
        raise ValueError("Sample owner is missing from contributor records.")
