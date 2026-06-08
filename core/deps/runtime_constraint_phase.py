from .drivers import DependencyRuntimeContext, get_dependency_drivers, get_registered_entity_types
from .gates import GateContext, PHASE_PRE_CONSTRAINT, evaluate_gates
from .runtime_impact import merge_impacts
from .runtime_trace import record_profile, timed_call


def _driver_entity_key(driver):
    etypes = tuple(driver.entity_types() or tuple())
    return etypes[0] if len(etypes) == 1 else "*"


def _source_ids(et, dirty):
    if et != "*":
        return set(dirty.get(et, set()) or set())
    ids = set()
    for values in dirty.values():
        ids |= set(values or set())
    return ids


def _constraint_gate(root, scene, gate_meta, et, ids):
    meta = dict(gate_meta or {})
    return evaluate_gates(GateContext(
        phase=PHASE_PRE_CONSTRAINT, root=root, scene=scene, source=str(meta.get("source", "unknown")),
        event_type=str(meta.get("event_type", "UPDATE")), entity_type=et, entity_ids=ids,
        payload=dict(meta.get("payload", {}) or {}),
    ))


def _filtered_dirty(dirty, filtered_ids):
    out = {k: set(v or set()) for k, v in dirty.items()}
    if filtered_ids is None:
        return out
    allowed = set(filtered_ids)
    for key in out:
        out[key] &= allowed
    return out


def _driver_context(root, scene, build, dirty, gate_meta, bake):
    return DependencyRuntimeContext(
        root=root, scene=scene, dirty=dirty, is_full=build.is_full, entity_sets=build.entity_sets,
        adjacency=build.adjacency, scc_idx=build.scc_idx, scc_sizes=build.scc_sizes,
        gate_meta=dict(gate_meta or {}), bake=bool(bake),
    )


def _run_driver(driver, ctx, profile):
    out, dt_ms = timed_call(driver.apply_constraints, ctx)
    record_profile(profile, "constraints", driver.name, dt_ms)
    return out or {}


def _driver_constraints(driver, root, scene, build, bake, gate_meta, profile):
    et = _driver_entity_key(driver)
    gate = _constraint_gate(root, scene, gate_meta, et, _source_ids(et, build.dirty))
    if not gate.allow:
        return {}
    ctx = _driver_context(root, scene, build, _filtered_dirty(build.dirty, gate.filtered_ids), gate_meta, bake)
    return _run_driver(driver, ctx, profile)


def apply_constraint_drivers(root, scene, build, bake, gate_meta=None, profile=None):
    extra = {et: set() for et in get_registered_entity_types()}
    for driver in get_dependency_drivers():
        merge_impacts(extra, _driver_constraints(driver, root, scene, build, bake, gate_meta, profile))
    return extra
