from .drivers import get_dependency_drivers
from .gates import GateContext, PHASE_PRE_SYNC, evaluate_gates
from .runtime_trace import record_profile, timed_call


def _merge_ids(groups):
    ids = set()
    for values in groups:
        ids |= set(values or set())
    return ids


def _driver_impacted(driver, impacted):
    etypes = tuple(driver.entity_types() or tuple())
    if not etypes:
        return "*", _merge_ids(impacted.values())
    if len(etypes) == 1:
        return etypes[0], set(impacted.get(etypes[0], set()) or set())
    return "*", _merge_ids(impacted.get(et, set()) for et in etypes)


def _sync_gate(root, scene, gate_meta, et, ids):
    meta = dict(gate_meta or {})
    return evaluate_gates(GateContext(
        phase=PHASE_PRE_SYNC, root=root, scene=scene, source=str(meta.get("source", "unknown")),
        event_type=str(meta.get("event_type", "UPDATE")), entity_type=et, entity_ids=ids,
        payload=dict(meta.get("payload", {}) or {}),
    ))


def _filtered_impacted(impacted, filtered_ids):
    out = {k: set(v or set()) for k, v in impacted.items()}
    if filtered_ids is None:
        return out, True
    allowed = set(filtered_ids)
    for key in out:
        out[key] &= allowed
    return out, False


def _has_ids(impacted):
    return any(bool(values) for values in impacted.values())


def _run_sync(driver, root, scene, is_full, impacted, bake, gate_meta, profile):
    _, dt_ms = timed_call(driver.sync, root, scene, is_full, impacted, bake, gate_meta)
    record_profile(profile, "sync", driver.name, dt_ms)


def _run_post_sync(driver, root, scene, is_full, impacted, bake, profile):
    _, dt_ms = timed_call(driver.post_sync, root, scene, is_full, impacted, bake)
    record_profile(profile, "post_sync", driver.name, dt_ms)


def _driver_sync(driver, root, scene, is_full, impacted, bake, gate_meta, profile):
    et, ids = _driver_impacted(driver, impacted)
    gate = _sync_gate(root, scene, gate_meta, et, ids)
    if not gate.allow:
        return
    d_impacted, keep_full = _filtered_impacted(impacted, gate.filtered_ids)
    if bool(is_full and keep_full) or _has_ids(d_impacted):
        _run_sync(driver, root, scene, bool(is_full and keep_full), d_impacted, bake, gate_meta, profile)


def run_sync_drivers(root, scene, is_full, impacted, bake, gate_meta=None, profile=None):
    for driver in get_dependency_drivers():
        _driver_sync(driver, root, scene, is_full, impacted, bake, gate_meta, profile)
    for driver in get_dependency_drivers():
        _run_post_sync(driver, root, scene, is_full, impacted, bake, profile)
