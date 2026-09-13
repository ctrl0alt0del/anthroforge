"""Blender-independent, serializable warning contracts."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps


@dataclass(frozen=True)
class EntityReference:
    epoch: str
    scene: str
    root: str
    kind: str
    native_id: str
    incarnation: int
    label: str = ""
    scene_label: str = ""
    root_label: str = ""
    authoring_id: str = ""

    @property
    def scope(self):
        return self.epoch, self.scene, self.root, self.kind, self.native_id, self.incarnation


@dataclass(frozen=True)
class PinReference:
    role: str
    index: int
    attachment_revision: int
    fingerprint: str


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


def fingerprint(value):
    return sha256(dumps(value, sort_keys=True, default=str).encode()).hexdigest()
