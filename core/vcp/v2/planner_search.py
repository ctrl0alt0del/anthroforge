"""Request-local contracts for deterministic roadmap attempts (no Blender state)."""

from dataclasses import dataclass, field
from enum import Enum


ROADMAP_POLICY_VERSION = "conditional-expanded-roadmap-1"


class RoadmapOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    GRAPH_DISCONNECTED = "GRAPH_DISCONNECTED"
    SEARCH_BUDGET_EXHAUSTED = "SEARCH_BUDGET_EXHAUSTED"
    CORRIDOR_VALIDATION_FAILED = "CORRIDOR_VALIDATION_FAILED"
    HANDOFF_COUNT_FAILED = "HANDOFF_COUNT_FAILED"
    HANDOFF_VALIDATION_FAILED = "HANDOFF_VALIDATION_FAILED"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_ATTACHMENT = "INVALID_ATTACHMENT"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class RoadmapPolicy:
    expanded: bool = False
    preparation: object = None
    observe_graph: object = None


PRODUCTION_ROADMAP_POLICY = RoadmapPolicy(expanded=True)


@dataclass(frozen=True)
class RoadmapAttempt:
    span: int
    strategy: str
    outcome: RoadmapOutcome
    nodes: int
    links: int
    searches: int = 0
    tested_pairs: int = 0
    search_ms: float = 0.0
    collision_ms: float = 0.0


@dataclass(frozen=True)
class RoadmapRecovery:
    span: int
    trigger: RoadmapOutcome
    outcome: RoadmapOutcome
    original_nodes: int
    expanded_nodes: int
    retained_links: int
    timings: tuple


@dataclass
class RoadmapSearchContext:
    span: int = 0
    last_graph: object = None
    attempts: list = field(default_factory=list)
    recoveries: list = field(default_factory=list)

    def start_span(self, index):
        self.span, self.last_graph = index, None

    def remember(self, points, neighbors):
        self.last_graph = (tuple(points), neighbors)

    def release(self):
        self.last_graph = None

    @property
    def outcome(self):
        return self.attempts[-1].outcome if self.attempts else RoadmapOutcome.GRAPH_DISCONNECTED


@dataclass(frozen=True)
class RoadmapPhaseTiming:
    phase: str
    elapsed_ms: float
