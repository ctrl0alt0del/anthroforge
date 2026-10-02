from dataclasses import dataclass, field
from time import monotonic


@dataclass
class RuntimeProgress:
    """Request-local recovery; application errors exist only during one execution."""
    accepted_dirty: dict = field(default_factory=dict)
    application_errors: list = field(default_factory=list)
    started: bool = False
    completed: bool = False

    def begin(self):
        self.application_errors.clear()
        self.started, self.completed = True, False

    def dirty_hints(self, original):
        if not self.accepted_dirty:
            return original
        merged = {key: set(values) for key, values in original.items()}
        for key, values in self.accepted_dirty.items():
            merged.setdefault(key, set()).update(values)
        return merged


@dataclass(frozen=True)
class RuntimeRequest:
    dirty_hints: dict = field(default_factory=dict)
    bake: bool = False
    source: str = "manual"
    event_type: str = "UPDATE"
    payload: dict = field(default_factory=dict)
    full: bool = False
    dirty_aspects: dict = field(default_factory=dict)
    quality: str = "INTERACTIVE"
    queued_at: float = field(default_factory=monotonic)
    progress: RuntimeProgress = field(default_factory=RuntimeProgress, compare=False)

    def gate_meta(self):
        return {"source": self.source, "event_type": self.event_type, "payload": dict(self.payload or {}),
                "full": self.full, "dirty_aspects": dict(self.dirty_aspects or {}), "quality": self.quality,
                "runtime_progress": self.progress}


def _request_full(dirty_hints, full):
    if full is not None:
        return bool(full)
    marked = getattr(dirty_hints, "full", None)
    return bool(marked) if marked is not None else dirty_hints is None or not dirty_hints


def _request_quality(quality, bake):
    value = str(quality or "").strip().upper()
    return "FINAL" if bake or value in {"BAKE", "FINAL"} else "INTERACTIVE"


def runtime_request(dirty_hints=None, bake=False, source="manual", event_type="UPDATE", payload=None,
                    full=None, dirty_aspects=None, quality="", queued_at=None):
    quality = _request_quality(quality, bake)
    return RuntimeRequest(dict(dirty_hints or {}), quality == "FINAL", str(source or "manual"),
                          str(event_type or "UPDATE"), dict(payload or {}), _request_full(dirty_hints, full),
                          dict(dirty_aspects or {}), quality,
                          monotonic() if queued_at is None else float(queued_at))


def seeded_dirty_hints(dirty_hints, entity_type, entity_id, dirty_hints_for, empty_dirty_hints):
    if dirty_hints is not None:
        return dirty_hints
    if entity_type and entity_id:
        return dirty_hints_for(entity_type, {entity_id})
    return empty_dirty_hints()
