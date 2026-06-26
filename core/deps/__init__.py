from .drivers import (
    DependencyDriver,
    DependencyRuntimeContext,
    register_dependency_driver,
    get_dependency_drivers,
    get_registered_entity_types,
)
from .dirty_hints import empty_dirty_hints, dirty_hints_for
from .gates import (
    PHASE_PRE_INGEST,
    PHASE_PRE_CONSTRAINT,
    PHASE_PRE_SYNC,
    GateContext,
    GateDecision,
    register_gate,
    evaluate_gates,
)
from .conflict_resolver import (
    resolve_conflict,
    register_conflict_strategy,
    list_conflict_strategies,
    set_conflict_policy,
    get_conflict_policy,
    list_conflict_policies,
    clear_conflict_policies,
)


def run_dependency_runtime(*args, **kwargs):
    from .runtime import run_dependency_runtime as runner
    return runner(*args, **kwargs)

__all__ = [
    "run_dependency_runtime",
    "get_registered_entity_types",
    "DependencyDriver",
    "DependencyRuntimeContext",
    "register_dependency_driver",
    "get_dependency_drivers",
    "empty_dirty_hints",
    "dirty_hints_for",
    "PHASE_PRE_INGEST",
    "PHASE_PRE_CONSTRAINT",
    "PHASE_PRE_SYNC",
    "GateContext",
    "GateDecision",
    "register_gate",
    "evaluate_gates",
    "resolve_conflict",
    "register_conflict_strategy",
    "list_conflict_strategies",
    "set_conflict_policy",
    "get_conflict_policy",
    "list_conflict_policies",
    "clear_conflict_policies",
]
