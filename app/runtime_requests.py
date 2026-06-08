from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeRequest:
    dirty_hints: dict = field(default_factory=dict)
    bake: bool = False
    source: str = "manual"
    event_type: str = "UPDATE"
    payload: dict = field(default_factory=dict)

    def gate_meta(self):
        return {"source": self.source, "event_type": self.event_type, "payload": dict(self.payload or {})}


def runtime_request(dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None):
    return RuntimeRequest(dict(dirty_hints or {}), bool(bake), str(source or "manual"), str(event_type or "UPDATE"), dict(payload or {}))


def seeded_dirty_hints(dirty_hints, entity_type, entity_id, dirty_hints_for, empty_dirty_hints):
    if dirty_hints is not None:
        return dict(dirty_hints or {})
    if entity_type and entity_id:
        return dirty_hints_for(entity_type, {entity_id})
    return empty_dirty_hints()
