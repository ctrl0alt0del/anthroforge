"""Python-only session identities, including explicit PropertyGroup retire boundaries."""
from uuid import uuid4
from time import perf_counter
from .model import EntityReference, fingerprint
from .repository import WarningRepository
from .coordinator import Coordinator

REPOSITORY = WarningRepository()
COORDINATOR = Coordinator(REPOSITORY)
from ..issues.system import IssueSystem
SYSTEM = IssueSystem(REPOSITORY, COORDINATOR)
from ..issues.api import configure
configure(SYSTEM)
EPOCH = uuid4().hex
_LEDGER, _SERIAL = {}, 0


def measure(name, callback, *args, **kwargs):
    started = perf_counter()
    try:
        return callback(*args, **kwargs)
    finally:
        elapsed = (perf_counter() - started) * 1000
        COORDINATOR.metrics[name + "_ms"] += elapsed
        COORDINATOR.metrics["max_" + name + "_ms"] = max(elapsed, COORDINATOR.metrics["max_" + name + "_ms"])


def id_token(value):
    uid = int(getattr(value, "session_uid", 0) or 0)
    return str(uid or pointer(value))


def pointer(value):
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError):
        return id(value)


def entity_reference(scene, root, entity, kind="FIBER"):
    global _SERIAL
    key = EPOCH, id_token(scene), id_token(root), kind, str(getattr(entity, "id", ""))
    prior = _LEDGER.get(key)
    if prior is None or prior[0] != pointer(entity):
        _SERIAL += 1
        _LEDGER[key] = pointer(entity), _SERIAL, 0, ""
    return EntityReference(*key, _LEDGER[key][1], str(getattr(entity, "name", "")),
                           str(getattr(scene, "name", "")), str(getattr(root, "name", "")),
                           authoring_id(entity))


def authoring_id(entity):
    getter = getattr(entity, "get", None)
    return str(getter("af_authoring_id", "") or "") if callable(getter) else ""


def attachment_identity(ref, specs):
    key, signature = ref.scope[:-1], fingerprint(specs)
    address, incarnation, revision, previous = _LEDGER[key]
    revision += int(signature != previous)
    _LEDGER[key] = address, incarnation, revision, signature
    return revision, signature


def retire(root=None, entity_ids=None):
    root_id = None if root is None else id_token(root)
    for key in tuple(_LEDGER):
        if (root_id is None or key[2] == root_id) and (entity_ids is None or key[4] in entity_ids):
            _LEDGER.pop(key)
    for scope in tuple(REPOSITORY.states):
        if (root_id is None or scope[2] == root_id) and (entity_ids is None or scope[4] in entity_ids):
            REPOSITORY.remove(scope)


def reset(state="UNSCANNED"):
    global EPOCH
    COORDINATOR.cancel_all()
    SYSTEM.reset()
    EPOCH = uuid4().hex
    _LEDGER.clear(); REPOSITORY.clear(state)


def scopes_for(scene=None, root=None, entity_ids=None):
    return tuple(scope for scope in REPOSITORY.states
                 if (scene is None or scope[1] == id_token(scene))
                 and (root is None or scope[2] == id_token(root))
                 and (entity_ids is None or scope[4] in entity_ids))
