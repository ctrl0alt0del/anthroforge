"""Typed immutable anatomical records, detached from Blender RNA."""
from dataclasses import dataclass, field
from typing import Mapping
from .model import freeze


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    ontology: str = ''


@dataclass(frozen=True)
class Entity:
    id: str
    concept: str
    side: str
    label: str
    evidence: Mapping


@dataclass(frozen=True)
class Relation:
    id: str
    subject: str
    predicate: str
    object: str
    evidence: Mapping


@dataclass(frozen=True)
class Claim:
    id: str
    subject: str
    property: str
    value: str | float | Mapping
    evidence: Mapping


@dataclass(frozen=True)
class SkeletonProfile:
    id: str
    reference_pose: str
    bindings: Mapping
    frames: Mapping
    controls: Mapping
    landmarks: Mapping
    regions: Mapping
    measurements: Mapping
    calibration: Mapping | None = None


@dataclass(frozen=True)
class Recipe:
    id: str
    strategy: str
    concept: str
    roles: Mapping
    construction: Mapping
    parameters: Mapping
    shape: str
    evidence: Mapping


@dataclass(frozen=True)
class Instance:
    id: str
    recipe: str
    profile: str
    bindings: Mapping
    shape: str
    parameters: Mapping
    policy: str
    side: str
    evidence: Mapping
    supports: Mapping = field(default_factory=lambda: freeze({}))
    evaluation_profile: str | None = None
    route_overrides: Mapping = field(default_factory=lambda: freeze({}))


@dataclass(frozen=True)
class Requirement:
    id: str
    target: str
    need: str
    depends_on: tuple[str, ...]
    consumers: tuple[str, ...]
    constraints: tuple[Mapping, ...]
    required_state: str
    evidence: Mapping


TYPES = dict(concepts=Concept, entities=Entity, relations=Relation, claims=Claim, skeleton_profiles=SkeletonProfile, recipes=Recipe, instances=Instance, requirements=Requirement)


def read_records(document, collection):
    return tuple(TYPES[collection](id=identity, **{k: freeze(v) for k, v in row.items()}) for identity, row in document.get(collection, {}).items())
