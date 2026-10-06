"""Immutable capture and result contracts; no Blender or native-library imports."""
from dataclasses import dataclass, field
from typing import Protocol
import numpy as np


@dataclass(frozen=True, order=True)
class DomainKey:
    root: str
    muscle: str
    instance: str = 'source'
    side: str = 'A'


@dataclass(frozen=True)
class DetectionSettings:
    search_distance: float = .05
    displacement: float = .5
    min_projected_area: float = 1e-10
    epsilon: float = 1e-9
    fragment_limit: int = 2000000
    workers: int = 4
    cache_bytes: int = 256 * 1024 * 1024
    result_bytes: int = 256 * 1024 * 1024
    stacking: object = None
    relationships: tuple = ()


@dataclass(frozen=True)
class DomainSnapshot:
    key: DomainKey
    group: str
    revision: str
    base: np.ndarray
    own: np.ndarray
    direction: np.ndarray
    faces: np.ndarray
    parts: np.ndarray
    sources: np.ndarray
    displacement: float = .5
    enabled: bool = True
    material: object = None
    output_indices: object = None
    obstacles: tuple = ()
    valid: bool = True


@dataclass(frozen=True)
class DetectionResult:
    generation: int
    status: str
    pairs: tuple = ()
    timings: dict = field(default_factory=dict)
    issues: tuple = ()
    geometry_only: bool = True
    activation_ready: bool = False
    stacking: dict = field(default_factory=dict)


class DetectionBackend(Protocol):
    def submit(self, domains, settings, generation): ...
    def poll(self): ...
    def summary(self): ...
    def footprint(self, index, generation): ...
    def cancel(self): ...
    def release(self): ...
    def close(self): ...


class DomainCapturePort(Protocol):
    def capture(self, scope, settings): ...


def immutable(value, dtype, shape):
    result = np.array(value, dtype=dtype, order='C', copy=True)
    if result.ndim != len(shape) or any(size is not None and size != actual for size, actual in zip(shape, result.shape)):
        raise ValueError('PAIR_ARRAY_SHAPE')
    result.flags.writeable = False
    return result


def snapshot(key, group, revision, base, own, direction, faces, parts, sources, displacement=.5, enabled=True):
    coords = [immutable(v, np.float64, (None, 3)) for v in (base, own, direction)]
    triangles = immutable(faces, np.int64, (None, 3))
    if not np.array_equal(triangles, faces): raise ValueError('PAIR_TRIANGLE_INDEX')
    if any(v.shape != coords[0].shape for v in coords): raise ValueError('PAIR_ARRAY_SHAPE')
    labels = [immutable(v, np.int64, (len(triangles),)) for v in (parts, sources)]
    if any(not np.array_equal(a, b) for a, b in zip(labels, (parts, sources))): raise ValueError('PAIR_PROVENANCE_INDEX')
    if key.side not in ('A', 'B'): raise ValueError('PAIR_SIDE')
    return DomainSnapshot(key, group or key.muscle, revision, *coords, triangles, *labels, displacement, enabled)
