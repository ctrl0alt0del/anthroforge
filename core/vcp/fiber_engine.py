"""Pure-data resumable Fiber request/session contracts."""

from dataclasses import dataclass, field
from enum import Enum


class FiberPhase(str, Enum):
    CAPTURE = "CAPTURE"
    COLLIDERS = "COLLIDERS"
    PLAN = "PLAN"
    LEVEL_SETUP = "LEVEL_SETUP"
    LOCAL_STEP = "LOCAL_STEP"
    CONTACTS = "CONTACTS"
    GLOBAL_STEP = "GLOBAL_STEP"
    LINE_SEARCH = "LINE_SEARCH"
    ACCEPT = "ACCEPT"
    FINAL_VALIDATE = "FINAL_VALIDATE"
    DONE = "DONE"


class FiberTermination(str, Enum):
    CONVERGED = "CONVERGED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    STALLED = "STALLED"
    BLOCKED = "BLOCKED"
    NO_FEASIBLE_PATH = "NO_FEASIBLE_PATH"
    UNSAFE_OUTPUT = "UNSAFE_OUTPUT"
    INVALID_ATTACHMENT = "INVALID_ATTACHMENT"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class FiberAnchorData:
    point: tuple
    owner_id: str = ""
    role: str = "TOUCH"


@dataclass(frozen=True)
class FiberColliderData:
    owner_id: str
    vertices: tuple
    triangles: tuple
    generation: tuple = ()


@dataclass(frozen=True)
class FiberEngineRequest:
    token: int
    quality: str
    topology: str
    node_count: int
    symmetry: tuple
    anchors: tuple
    settings: tuple
    colliders: tuple
    warm_seed: tuple = ()


@dataclass
class FiberEngineState:
    request: FiberEngineRequest
    phase: FiberPhase = FiberPhase.CAPTURE
    termination: object = None
    generation: int = 0
    telemetry: dict = field(default_factory=dict)

    def advance(self, phase):
        self.phase = FiberPhase(phase)
        self.generation += 1
        return self.phase

    def finish(self, reason):
        self.termination = FiberTermination(reason)
        self.advance(FiberPhase.DONE)
        return self.termination
