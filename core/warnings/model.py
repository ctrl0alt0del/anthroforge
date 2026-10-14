"""Compatibility contracts for the attachment warning subsystem."""
from dataclasses import asdict, dataclass
from ..issues.model import EntityReference, PinReference, fingerprint


@dataclass(frozen=True)
class Warning:
    entity: EntityReference
    pin: PinReference | None
    code: str
    summary: str
    details: str
    evidence: tuple
    related: tuple = ()
    source_generation: int = 0
    provider: str = "fiber_hard_anchor.v1"
    severity: str = "warning"

    @property
    def key(self):
        pin = None if self.pin is None else (self.pin.role, self.pin.index)
        return self.entity.scope, self.provider, self.code, pin, dict(self.evidence).get("blocker_id", "")

    @property
    def id(self):
        return fingerprint(self.key)

    def serialize(self, state, revision):
        value = asdict(self)
        value.update(id=self.id, evidence=dict(self.evidence), check_state=state,
                     freshness="current" if state == "COMPLETE" else "stale", repository_revision=revision)
        return value
