from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set


PHASE_PRE_INGEST = "PRE_INGEST"
PHASE_PRE_CONSTRAINT = "PRE_CONSTRAINT"
PHASE_PRE_SYNC = "PRE_SYNC"
PHASE_PRE_WRITEBACK = "PRE_WRITEBACK"


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
    PHASE_PRE_WRITEBACK: [],
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


def allow_writeback(
    *,
    root,
    scene,
    source,
    event_type,
    entity_type,
    entity_id,
    payload=None,
):
    ctx = GateContext(
        phase=PHASE_PRE_WRITEBACK,
        root=root,
        scene=scene,
        source=source,
        event_type=event_type,
        entity_type=entity_type,
        entity_ids={str(entity_id)} if entity_id else set(),
        payload=payload or {},
    )
    d = evaluate_gates(ctx)
    if not d.allow:
        return False
    if d.filtered_ids is None:
        return True
    return str(entity_id) in d.filtered_ids


def _gate_user_transform_required(ctx: GateContext) -> GateDecision:
    if ctx.phase != PHASE_PRE_WRITEBACK:
        return GateDecision(allow=True)

    req = str((ctx.payload or {}).get("require_user_transform", "")).upper()
    if not req:
        return GateDecision(allow=True)

    checker = (ctx.payload or {}).get("is_user_transform_active")
    if not callable(checker):
        return GateDecision(allow=True)

    active = bool(checker(req))
    if active:
        return GateDecision(allow=True)
    return GateDecision(allow=False, reason="user transform gate blocked writeback")


def _gate_skip_synced_matrix(ctx: GateContext) -> GateDecision:
    if ctx.phase != PHASE_PRE_WRITEBACK:
        return GateDecision(allow=True)

    if not bool((ctx.payload or {}).get("check_synced_matrix", False)):
        return GateDecision(allow=True)

    obj = (ctx.payload or {}).get("obj")
    fn = (ctx.payload or {}).get("is_synced_matrix_fn")
    if obj is None or not callable(fn):
        return GateDecision(allow=True)

    if bool(fn(obj)):
        return GateDecision(allow=False, reason="synced matrix gate blocked writeback")
    return GateDecision(allow=True)


register_gate(PHASE_PRE_WRITEBACK, _gate_user_transform_required, priority=10)
register_gate(PHASE_PRE_WRITEBACK, _gate_skip_synced_matrix, priority=20)

