from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set


PHASE_PRE_INGEST = "PRE_INGEST"
PHASE_PRE_CONSTRAINT = "PRE_CONSTRAINT"
PHASE_PRE_SYNC = "PRE_SYNC"


@dataclass
class GateContext:
    phase: str
    root: object = None
    scene: object = None
    source: str = "unknown"
    event_type: str = "UPDATE"
    entity_type: str = ""
    entity_ids: Set[str] = field(default_factory=set)
    payload: dict = field(default_factory=dict)


@dataclass
class GateDecision:
    allow: bool = True
    filtered_ids: Optional[Set[str]] = None
    reason: str = ""


_GATES: Dict[str, List[tuple[int, Callable[[GateContext], GateDecision]]]] = {
    PHASE_PRE_INGEST: [],
    PHASE_PRE_CONSTRAINT: [],
    PHASE_PRE_SYNC: [],
}


def register_gate(phase: str, gate_fn: Callable[[GateContext], GateDecision], priority: int = 100):
    if phase not in _GATES:
        raise ValueError(f"unknown gate phase: {phase}")
    if not callable(gate_fn):
        raise TypeError("gate_fn must be callable")
    _GATES[phase].append((int(priority), gate_fn))
    _GATES[phase].sort(key=lambda x: x[0])


def evaluate_gates(ctx: GateContext) -> GateDecision:
    gates = _GATES.get(ctx.phase, ())
    if not gates:
        return GateDecision(allow=True, filtered_ids=None, reason="")

    allowed_ids = set(ctx.entity_ids or set())
    had_filter = False

    for _prio, gate in gates:
        d = gate(ctx)
        if not d.allow:
            return d
        if d.filtered_ids is not None:
            had_filter = True
            allowed_ids &= set(d.filtered_ids)

    return GateDecision(allow=True, filtered_ids=allowed_ids if had_filter else None, reason="")


