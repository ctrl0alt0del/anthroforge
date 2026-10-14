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


def fingerprint(value):
    return sha256(dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class Issue:
    entity: EntityReference
    code: str
    summary: str
    details: str = ""
    evidence: tuple = ()
    provider: str = ""
    stage: str = ""
    artifact_revision: str = ""
    local_key: str = ""
    severity: str = "warning"
    source_generation: int = 0
    related: tuple = ()
    pin: PinReference | None = None

    def __post_init__(self):
        object.__setattr__(self, "evidence", tuple((key, freeze(value)) for key, value in self.evidence))
        object.__setattr__(self, "related", tuple(self.related))

    @property
    def key(self):
        return self.entity.scope, self.provider, self.stage, self.artifact_revision, self.code, self.local_key

    @property
    def id(self):
        return fingerprint(self.key)

    def serialize(self, state, revision):
        return dict(asdict(self), id=self.id, evidence=dict(self.evidence), check_state=state,
                    freshness="current" if state == "COMPLETE" else "stale", repository_revision=revision)


class FrozenDict(dict):
    def _blocked(self, *_args, **_kwargs):
        raise TypeError("Issue evidence is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _blocked

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    if isinstance(value, dict):
        return FrozenDict((key, freeze(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value
