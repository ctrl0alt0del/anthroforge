"""Data-only contract for topology update strategies; numerical solvers belong in C++."""
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class TopologyUpdateOptions:
    strategy: str = "current"
    version: int = 1
    module: str = ""
    failure_policy: str = "REBUILD"
    settings: dict = field(default_factory=dict)
    maximum_surface_error: float | None = None


@dataclass(frozen=True)
class TopologyUpdateContext:
    topology: Any
    before_skin: Any
    after_skin: Any
    capture: Any
    skin_update: str
    settings: dict = field(default_factory=dict)
    before_sources: tuple = ()
    after_sources: tuple = ()
    memory_budget: int = 0
    cancelled: Callable[[], bool] | None = None
    predicted: Any = None
    deformation_reference: Any = None
    anatomy_targets: Any = None
    cancel_path: str = ""
    contact_projection: Any = None
    prepared_solver: Any = None


@dataclass(frozen=True)
class TopologyUpdateCandidate:
    vertices: Any
    vertex_ids: Any
    skin_binding: Any
    guide_binding: Any
    accepted: bool = True
    message: str = ""
    diagnostics: dict = field(default_factory=dict)
    deformation: dict | None = None


@dataclass(frozen=True)
class TopologyUpdateOutcome:
    result: Any = None
    diagnostics: dict = field(default_factory=dict)


class TopologyUpdateStrategy(Protocol):
    name: str
    version: int

    def solve(self, context: TopologyUpdateContext) -> TopologyUpdateCandidate: ...


class TopologyUpdateStopped(RuntimeError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(diagnostics.get("message", "Topology update stopped."))


class TopologyCandidateRejected(ValueError):
    def __init__(self, message, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(message)
