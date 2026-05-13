from dataclasses import dataclass, field


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
class FiberSnapshot:
    source_id: str
    name: str
    props: dict
    a_parent_id: str
    b_parent_id: str
    muscle_id: str
    touches: list[FiberTouchSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        items = [FiberTouchSnapshot.from_dict(x) for x in data.pop("touches", ())]
        return cls(touches=items, **data)


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
class ShortcutSnapshot:
    name: str
    owner_type: str
    owner_id: str
    data_path: str

    @classmethod
    def from_dict(cls, data):
        return cls(**dict(data or {}))


@dataclass
class PackageSnapshot:
    root_name: str
    scps: list[ScpSnapshot] = field(default_factory=list)
    fibers: list[FiberSnapshot] = field(default_factory=list)
    muscles: list[MuscleSnapshot] = field(default_factory=list)
    blobs: list[BlobSnapshot] = field(default_factory=list)
    shortcuts: list[ShortcutSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        data["scps"] = [ScpSnapshot.from_dict(x) for x in data.get("scps", ())]
        data["fibers"] = [FiberSnapshot.from_dict(x) for x in data.get("fibers", ())]
        data["muscles"] = [MuscleSnapshot.from_dict(x) for x in data.get("muscles", ())]
        data["blobs"] = [BlobSnapshot.from_dict(x) for x in data.get("blobs", ())]
        data["shortcuts"] = [ShortcutSnapshot.from_dict(x) for x in data.get("shortcuts", ())]
        return cls(**data)


@dataclass
class ImportResult:
    scp_count: int = 0
    fiber_count: int = 0
    muscle_count: int = 0
    blob_count: int = 0
    shortcut_count: int = 0
    warnings: list[str] = field(default_factory=list)
    kept_objects: list[object] = field(default_factory=list, repr=False)
