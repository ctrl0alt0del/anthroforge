from dataclasses import dataclass, field

try:
    from ..draft_skin.settings import root_settings_percentages
    from ..topology.settings import default_settings_payload as default_topology_settings
except ImportError:
    from core.draft_skin.settings import root_settings_percentages
    from core.topology.settings import default_settings_payload as default_topology_settings


def _default_draft_skin_settings():
    return root_settings_percentages()


@dataclass
class BoundObjectSnapshot:
    bound_id: str
    label: str
    object_name: str

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class ScpSnapshot:
    source_id: str
    name: str
    parent_id: str
    props: dict
    transform_bound_id: str = ""
    geometry_bound_id: str = ""
    topology: object = None
    bound_objects: list[BoundObjectSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        items = [BoundObjectSnapshot.from_dict(x) for x in data.pop("bound_objects", ())]
        return cls(bound_objects=items, **data)


@dataclass
class FiberTouchSnapshot:
    parent_id: str
    props: dict

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class FiberLoopAnchorSnapshot:
    parent_id: str
    props: dict

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class FiberSnapshot:
    source_id: str
    name: str
    props: dict
    a_parent_id: str
    b_parent_id: str
    muscle_id: str
    touches: list[FiberTouchSnapshot] = field(default_factory=list)
    loop_anchors: list[FiberLoopAnchorSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        touches = [FiberTouchSnapshot.from_dict(x) for x in data.pop("touches", ())]
        anchors = [FiberLoopAnchorSnapshot.from_dict(x) for x in data.pop("loop_anchors", ())]
        data.pop("driver_fiber_id", None)
        data.pop("loop_profile_keys", None)
        return cls(touches=touches, loop_anchors=anchors, **data)


@dataclass
class MuscleSnapshot:
    source_id: str
    name: str
    props: dict
    fiber_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class BlobSnapshot:
    source_id: str
    name: str
    props: dict
    attach_target_type: str
    attach_target_id: str
    attach_target_object_name: str
    attach_object_entity: str = ""

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class SoftTissueAttachmentSnapshot:
    props: dict

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class SoftTissueSnapshot:
    source_id: str
    name: str
    props: dict
    host_scp_id: str = ""
    base_object_name: str = ""
    attachments: list[SoftTissueAttachmentSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        values = dict(data or {})
        rows = [SoftTissueAttachmentSnapshot.from_dict(x) for x in values.pop("attachments", ())]
        return cls(attachments=rows, **values)


@dataclass
class ShortcutOverrideSnapshot:
    target_scp_id: str
    parent_anchor_mode: str = "KEEP"
    child_anchor_mode: str = "KEEP"
    follow_rotation_mode: str = "KEEP"
    rotation_strategy: str = "KEEP"

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class ShortcutSnapshot:
    name: str
    owner_type: str
    owner_id: str
    data_path: str
    vector_mode: str = "DEFAULT"
    owner_backsolve: bool = True
    overrides: list[ShortcutOverrideSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        data["overrides"] = [ShortcutOverrideSnapshot.from_dict(x) for x in data.get("overrides", ())]
        return cls(**data)


@dataclass
class PackageSnapshot:
    root_name: str
    scps: list[ScpSnapshot] = field(default_factory=list)
    fibers: list[FiberSnapshot] = field(default_factory=list)
    muscles: list[MuscleSnapshot] = field(default_factory=list)
    blobs: list[BlobSnapshot] = field(default_factory=list)
    soft_tissues: list[SoftTissueSnapshot] = field(default_factory=list)
    shortcuts: list[ShortcutSnapshot] = field(default_factory=list)
    draft_skin_settings: dict = field(default_factory=_default_draft_skin_settings)
    topology_settings: dict = field(default_factory=default_topology_settings)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        data.setdefault("draft_skin_settings", _default_draft_skin_settings())
        data.setdefault("topology_settings", default_topology_settings())
        data["scps"] = [ScpSnapshot.from_dict(x) for x in data.get("scps", ())]
        data["fibers"] = [FiberSnapshot.from_dict(x) for x in data.get("fibers", ())]
        data["muscles"] = [MuscleSnapshot.from_dict(x) for x in data.get("muscles", ())]
        data["blobs"] = [BlobSnapshot.from_dict(x) for x in data.get("blobs", ())]
        data["soft_tissues"] = [SoftTissueSnapshot.from_dict(x) for x in data.get("soft_tissues", ())]
        data["shortcuts"] = [ShortcutSnapshot.from_dict(x) for x in data.get("shortcuts", ())]
        return cls(**data)


@dataclass
class ImportResult:
    scp_count: int = 0
    fiber_count: int = 0
    muscle_count: int = 0
    blob_count: int = 0
    soft_tissue_count: int = 0
    shortcut_count: int = 0
    warnings: list[str] = field(default_factory=list)
    kept_objects: list[object] = field(default_factory=list, repr=False)
