"""Shared authoring records, immutable intent, execution budgets and ports."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol
from time import perf_counter
import numpy as np
from .errors import require


def readonly(value, dtype=float):
    array = np.array(value, dtype=dtype, copy=True)
    array.flags.writeable = False
    return array


@dataclass(frozen=True)
class MeshSnapshot:
    id: str
    vertices: np.ndarray
    triangles: np.ndarray
    matrix: np.ndarray
    concept: str = ""
    side: str = "midline"
    label: str = ""


@dataclass(frozen=True)
class SceneSnapshot:
    id: str
    revision: str
    meshes: tuple
    pose: str = "rest"


@dataclass(frozen=True)
class Anchor:
    owner: str
    point: tuple
    normal: tuple
    surface: tuple
    offset: float
    surface_binding: tuple | None = None


@dataclass(frozen=True)
class FiberPlan:
    id: str
    u: float
    anchors: tuple
    stations: tuple
    count: int
    closed: bool
    collision_radius: float = .002


class ScenePort(Protocol):
    def capture(self, scene_id: str) -> SceneSnapshot: ...
    def publish(self, snapshot, document, result, previous): ...


class SolverPort(Protocol):
    def solve(self, plan: FiberPlan, snapshot: SceneSnapshot, budget_ms: int): ...


class ContactPort(Protocol):
    def evaluate(self, vertices, quads, snapshot: SceneSnapshot, tolerance: float): ...


class StorePort(Protocol):
    def get(self, category: str, key): ...
    def put(self, category: str, key, value): ...
    def asset(self, value, kind="geometry"): ...
    def image(self, content: str): ...


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    return tuple(map(freeze, value)) if isinstance(value, list) else value


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    return list(map(plain, value)) if isinstance(value, tuple) else value


@dataclass(frozen=True)
class Document:
    id: str
    revision: int
    content: Mapping

    @classmethod
    def read(cls, data):
        return cls(data['document_id'], data['revision'], freeze(data))

    def records(self, collection):
        from .records import read_records
        return read_records(plain(self.content), collection)


@dataclass(frozen=True)
class AnatomicalRecord:
    id: str
    kind: str
    definition: Mapping


@dataclass(frozen=True)
class Candidate:
    id: str
    requirement_id: str
    provider: str
    proposal: Mapping
    checks: tuple
    inputs_digest: str


@dataclass(frozen=True)
class Evaluation:
    inputs_digest: str
    state: str
    outputs: Mapping
    diagnostics: tuple


@dataclass
class Budget:
    milliseconds: float = 30000
    maximum: int = 100000
    cancelled: bool = False
    started: float = field(default_factory=perf_counter)
    consumed: int = 0

    def check(self, count=1):
        self.consumed += count
        require(not self.cancelled, 'CANCELLED')
        require(self.consumed <= self.maximum, 'SAMPLE_BUDGET_EXHAUSTED')
        require((perf_counter()-self.started)*1000 <= self.milliseconds, 'TIME_BUDGET_EXHAUSTED')


class InventoryPort(Protocol):
    def capture_authoring(self): ...
    def capture(self, scene_id): ...


class IdentityPort(Protocol):
    def initialize(self): ...
    def remember_journal(self, directory): ...


class PublicationPort(Protocol):
    def publish(self, captured, document, outputs, previous): ...
    def persist(self, record): ...
    def owned_records(self, identities): ...


class NativeEditPort(Protocol):
    def native_changes(self, published): ...
    def authorize_restore(self, identity): ...
    def attachment_points(self, fiber_record): ...
    def restoration(self, identity): ...


class CandidateProvider(Protocol):
    def preflight(self, context, requirement, parameters): ...
    def propose(self, context, requirement, parameters, budget): ...


class PreviewPort(Protocol):
    def render(self, inventory, geometry, title): ...


class CheckpointPort(Protocol):
    def save_checkpoint(self, path, generation): ...


class Registry:
    def __init__(self):
        self.entries = {}

    def add(self, name, strategy):
        require(name not in self.entries, 'DUPLICATE_STRATEGY', name)
        self.entries[name] = strategy

    def get(self, name):
        require(name in self.entries, 'UNSUPPORTED_CAPABILITY', name)
        return self.entries[name]
