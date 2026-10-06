"""Owned material correspondence and persisted stacking configuration contracts."""
from dataclasses import dataclass
from ..muscle_pairs.model import immutable


@dataclass(frozen=True)
class StackingSettings:
    enabled: bool = True
    clearance: float = 0.
    radius: float = .2
    strength: float = .8
    exclusions: tuple = ()


@dataclass(frozen=True)
class Material:
    vertices: object
    faces: object
    interpolation: object
    weights: object
    fixed: object


def material(vertices, faces, interpolation, weights, fixed=()):
    width = interpolation.shape[1]
    return Material(immutable(vertices, float, (None, 3)), immutable(faces, 'int64', (None, 3)),
        immutable(interpolation, 'int64', (None, width)), immutable(weights, float, (None, width)),
        immutable(fixed, 'int64', (None,)))
