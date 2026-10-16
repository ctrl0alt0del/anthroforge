from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TopologySettings:
    target_quad_count: int = 8100
    symmetry_mode: str = "X"
    custom_origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    custom_normal: tuple[float, float, float] = (1.0, 0.0, 0.0)
    refinement_strategy: str = "NONE"
    backend: str = "QUADWILD"


@dataclass(frozen=True)
class TopologyDensityRule:
    scp_index: int
    scp_id: str
    parent_id: str
    mode: str = "INHERIT"
    subtree_quads: int = 0


@dataclass(frozen=True)
class TopologyOwnershipSource:
    source_index: int
    entity_type: str
    entity_id: str
    mirror_role: str
    owner_scp_ids: tuple[str, ...]
    vertices: Any
    triangles: Any


@dataclass(frozen=True)
class TopologyBudgetRegion:
    scp_id: str
    requested_quads: int
    exclusive_quads: int
    owner_indices: tuple[int, ...]
    area: float = 0.0


@dataclass(frozen=True)
class TopologyOwnership:
    owner_indices: Any
    fallback_count: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopologyDensityField:
    target_edge_lengths: Any
    regions: tuple[TopologyBudgetRegion, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SymmetryPlane:
    origin: Any
    normal: Any


@dataclass(frozen=True)
class TopologyGuide:
    guide_index: int
    fiber_id: str
    object_name: str
    mirror_role: str
    points: Any


@dataclass(frozen=True)
class TopologyCapture:
    root_name: str
    vertices: Any
    triangles: Any
    guides: tuple[TopologyGuide, ...]
    lower: Any
    upper: Any
    input_hash: str
    settings: TopologySettings = field(default_factory=TopologySettings)
    plane: SymmetryPlane | None = None
    warnings: tuple[str, ...] = ()
    density_rules: tuple[TopologyDensityRule, ...] = ()
    ownership_sources: tuple[TopologyOwnershipSource, ...] = ()
    flow_samples: Any = None
    flow_guides: tuple[TopologyGuide, ...] = ()


@dataclass(frozen=True)
class TopologyJobSpec:
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
class TopologyJobStatus:
    state: str = "PENDING"
    stage: str = "Waiting"
    progress: float = 0.0
    message: str = ""
    warnings: tuple[str, ...] = ()
    cancelled: bool = False


@dataclass(frozen=True)
class TopologyValidationReport:
    valid: bool
    finite: bool
    all_quads: bool
    connected: bool
    orientable: bool
    manifold: bool
    no_degenerates: bool
    boundary_match: bool
    guide_preserved: bool
    symmetry_ok: bool
    fidelity_ok: bool
    valence_ok: bool
    self_intersections: int = 0
    message: str = ""


@dataclass(frozen=True)
class TopologyResult:
    vertices: Any
    quads: Any
    face_regions: Any
    guide_indices: Any
    statistics: dict[str, Any] = field(default_factory=dict)
    validation: TopologyValidationReport | None = None
    owner_scp_indices: Any = None
    target_edge_lengths: Any = None
    skin_binding: Any = None
    guide_binding: Any = None
