from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WarmInvalidationReason(str, Enum):
    NONE = "NONE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    STRUCTURE_CHANGED = "STRUCTURE_CHANGED"
    SOURCE_IDENTITY_CHANGED = "SOURCE_IDENTITY_CHANGED"
    SOURCE_CONNECTIVITY_CHANGED = "SOURCE_CONNECTIVITY_CHANGED"
    SOLVER_SETTINGS_CHANGED = "SOLVER_SETTINGS_CHANGED"
    GUIDE_LAYOUT_CHANGED = "GUIDE_LAYOUT_CHANGED"
    BINDING_QUALITY = "BINDING_QUALITY"
    COLLISION_FAILURE = "COLLISION_FAILURE"
    VALIDATION_FAILED = "VALIDATION_FAILED"


@dataclass(frozen=True)
class SkinWarmBinding:
    source_indices: Any
    triangle_indices: Any
    barycentric: Any
    weights: Any
    normal_offsets: Any
    support: Any
    schema: int = 1


@dataclass(frozen=True)
class TopologySkinBinding:
    triangle_indices: Any
    barycentric: Any
    offsets: Any
    schema: int = 1


@dataclass(frozen=True)
class TopologyGuideBinding:
    guide_indices: Any
    rows: Any
    parameters: Any
    schema: int = 1


@dataclass(frozen=True)
class WarmValidationReport:
    valid: bool
    finite: bool
    no_inversions: bool
    containment: bool
    binding_coverage: float
    displacement_p95: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class WarmUpdateStatus:
    valid: bool
    stage: str
    progress: float
    message: str = ""
    reason: WarmInvalidationReason = WarmInvalidationReason.NONE
    warnings: tuple[str, ...] = ()
    state: str = "PENDING"
    cancelled: bool = False
    update_type: str = ""


@dataclass(frozen=True)
class SkinWarmCapture:
    vertices: Any
    triangles: Any
    binding: SkinWarmBinding
    old_sources: tuple[Any, ...]
    new_sources: tuple[Any, ...]
    structural_signature: str
    source_connectivity_signature: str
    geometry_state_hash: str
    solver_settings_hash: str
    source_identity_signature: str = ""
    expected_source_connectivity_signature: str = ""
    expected_source_identity_signature: str = ""
    expected_structural_signature: str = ""
    expected_solver_settings_hash: str = ""


@dataclass(frozen=True)
class SkinWarmResult:
    vertices: Any
    binding: SkinWarmBinding
    status: WarmUpdateStatus
    validation: WarmValidationReport | None = None
    statistics: dict[str, Any] = field(default_factory=dict)
