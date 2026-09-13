"""Repository publication and AF-6 compatibility; numerical caches stay in preflight."""
from dataclasses import asdict
from .model import PinReference, Warning
from .session import REPOSITORY, attachment_identity, entity_reference, scopes_for

CODE = "FIBER_INVALID_HARD_ANCHOR"
PROVIDER = "fiber_hard_anchor.v1"


def identity(scene, root, fiber):
    from ..vcp.fiber_anchor_preflight import _raw_anchor_specs
    ref = entity_reference(scene, root, fiber)
    try:
        specs = _raw_anchor_specs(fiber)
    except AttributeError:
        specs = ()
    return ref, attachment_identity(ref, specs)


def publish(scene, root, fiber, result, generation=0):
    ref, (revision, signature) = identity(scene, root, fiber)
    rows = tuple(record(ref, revision, signature, value, generation, related_entities(scene, root, value)) for value in result.violations)
    metadata = (result.cache_key, result.candidate_pairs, result.tested_pairs, result.anchors, revision, signature)
    REPOSITORY.replace(ref.scope, rows, generation, metadata)
    return ref.scope


def record(ref, revision, signature, value, generation, related=()):
    evidence = asdict(value)
    evidence["role"] = value.role.value
    role, index = value.role.value, value.authored_index
    pin = PinReference(role, index, revision, signature)
    summary = f"{role.replace('_', ' ').title()} {index}: blocked by {value.blocker_id}"
    return Warning(ref, pin, CODE, summary, value.action, tuple(evidence.items()), related, generation)


def related_entities(scene, root, value):
    ids = {value.owner_id, value.blocker_id}
    rows = getattr(getattr(root, "af_scp_system", None), "scps", ())
    return tuple(entity_reference(scene, root, row, "SCP") for row in rows if str(row.id) in ids)


def current(scene, root, fiber):
    ref, attachment = identity(scene, root, fiber)
    state = REPOSITORY.states.get(ref.scope, {})
    metadata = REPOSITORY.metadata.get((ref.scope, PROVIDER))
    valid = state.get("status") == "COMPLETE" and metadata is not None and metadata[-2:] == attachment
    return result_for_scope(ref.scope) if valid else None


def result_for_scope(scope):
    from ..vcp.fiber_anchor_preflight import FiberAnchorPreflightResult, FiberAnchorViolation
    from ..vcp.v2.contracts import V2AnchorRole
    metadata = REPOSITORY.metadata.get((scope, PROVIDER))
    if metadata is None:
        return None
    rows = [dict(REPOSITORY.records[key].evidence) for key in sorted(REPOSITORY.scopes.get(scope, ()))]
    violations = tuple(FiberAnchorViolation(**dict(row, role=V2AnchorRole(row["role"]))) for row in rows)
    violations = tuple(sorted(violations, key=lambda row: (row.authored_index, row.role.value, row.blocker_id)))
    key, candidates, tested, anchors = metadata[:4]
    return FiberAnchorPreflightResult(not violations, violations, key, candidates, tested, anchors)


def invalidate(scene=None, root=None, entity_ids=None):
    for scope in scopes_for(scene, root, entity_ids):
        REPOSITORY.state(scope, "PENDING", REPOSITORY.states[scope]["generation"] + 1)
