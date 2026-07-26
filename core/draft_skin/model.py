from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkinSource:
    source_index: int
    entity_type: str
    entity_id: str
    mirror_role: str
    object_name: str
    vertices: Any
    triangles: Any
    collagen: Any = None


@dataclass(frozen=True)
class SkinCapture:
    root_name: str
    sources: tuple[SkinSource, ...]
    lower: Any
    upper: Any
    input_hash: str
    voxel_size: float
    resolution: int = 220
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkinJobSpec:
    protocol_version: int
    solver_version: str
    root_name: str
    input_hash: str
    job_dir: str
    source_path: str
    input_path: str
    result_path: str
    status_path: str
    log_path: str
    cancel_path: str


@dataclass(frozen=True)
class SkinJobStatus:
    state: str = "PENDING"
    stage: str = "Waiting"
    progress: float = 0.0
    message: str = ""
    warnings: tuple[str, ...] = ()
    cancelled: bool = False


@dataclass(frozen=True)
class SkinValidationReport:
    valid: bool
    finite: bool
    connected: bool
    watertight: bool
    orientable: bool
    positive_volume: bool
    no_degenerates: bool
    source_inside: bool
    message: str = ""


@dataclass(frozen=True)
class SkinResult:
    vertices: Any
    triangles: Any
    collagen: Any
    statistics: dict[str, Any] = field(default_factory=dict)
    validation: SkinValidationReport | None = None
