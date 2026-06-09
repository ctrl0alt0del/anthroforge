from collections import defaultdict
from dataclasses import dataclass, field

try:
    from ...app.context import addon_context
    from ...app.runtime_intents import dispatch_runtime_intent as dispatch_app_runtime_intent
except ImportError:
    from app.context import addon_context
    from app.runtime_intents import dispatch_runtime_intent as dispatch_app_runtime_intent
from .dirty_hints import dirty_hints_for, empty_dirty_hints


@dataclass(frozen=True)
class RuntimeIntent:
    intent_type: str
    entity_type: str = ""
    entity_id: str = ""
    payload: dict = field(default_factory=dict)
    source: str = "manual"
    event_type: str = "UPDATE"


_RUNTIME_INTENTS = defaultdict(list)


def _root_key(root):
    return str(getattr(root, "name", "") or "")


def enqueue_runtime_intent(root, intent_type, entity_type="", entity_id="", payload=None, source="manual", event_type="UPDATE"):
    key = _root_key(root)
    if not key:
        return False
    _RUNTIME_INTENTS[key].append(_intent(intent_type, entity_type, entity_id, payload, source, event_type))
    return True


def _intent(intent_type, entity_type, entity_id, payload, source, event_type):
    return RuntimeIntent(
        intent_type=str(intent_type or ""),
        entity_type=str(entity_type or ""),
        entity_id=str(entity_id or ""),
        payload=dict(payload or {}),
        source=str(source or "manual"),
        event_type=str(event_type or "UPDATE"),
    )


def pop_runtime_intents(root):
    key = _root_key(root)
    if not key:
        return []
    return list(_RUNTIME_INTENTS.pop(key, []))


def dispatch_runtime_intent(root=None, scene=None, intent_type="", entity_type="", entity_id="", payload=None, dirty_hints=None, source="manual", event_type="UPDATE"):
    dispatch_app_runtime_intent(
        addon_context(root=root, scene=scene),
        enqueue_runtime_intent,
        _sync_fn(),
        dirty_hints_for,
        empty_dirty_hints,
        intent_type=intent_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        dirty_hints=dirty_hints,
        source=source,
        event_type=event_type,
    )


def _sync_fn():
    from ..visualization.sync_runner import sync_from_dirty_hints
    return sync_from_dirty_hints


def _run_sync(root, scene, dirty_hints, source, event_type):
    from ..visualization.sync_runner import sync_from_dirty_hints
    sync_from_dirty_hints(root=root, scene=scene, dirty_hints=dirty_hints, source=source, event_type=event_type)


def _seed_dirty_hints(dirty_hints, entity_type, entity_id):
    if dirty_hints is not None:
        return dict(dirty_hints or {})
    if entity_type and entity_id:
        return dirty_hints_for(entity_type, {entity_id})
    return empty_dirty_hints()
