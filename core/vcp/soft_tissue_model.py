from dataclasses import asdict, dataclass, field
from enum import Enum


Vec3 = tuple[float, float, float]
SCHEMA_VERSION = 1


class BaseDomain(str, Enum):
    POINT = "POINT"
    CURVE = "CURVE"
    SURFACE = "SURFACE"


class TissuePreset(str, Enum):
    CUSTOM = "CUSTOM"
    CLOSED_BULK = "CLOSED_BULK"
    RIM = "RIM"
    LAYER = "LAYER"
    POUCH = "POUCH"


class BoundaryMode(str, Enum):
    CLOSED = "CLOSED"
    HOST_SEALED = "HOST_SEALED"


class InflationMode(str, Enum):
    RADIAL = "RADIAL"
    NORMAL = "NORMAL"
    PROFILE = "PROFILE"


class AttachmentMode(str, Enum):
    FREE = "FREE"
    FIXED = "FIXED"
    SOFT = "SOFT"


class TargetKind(str, Enum):
    NONE = "NONE"
    SCP = "SCP"


class TargetSurface(str, Enum):
    AUTO = "AUTO"
    SCP_GEOMETRY = "SCP_GEOMETRY"


class SolverMode(str, Enum):
    NONE = "NONE"
    GEOMETRIC = "GEOMETRIC"
    STATIC_PBD = "STATIC_PBD"


@dataclass(frozen=True)
class BaseObjectSpec:
    domain: BaseDomain
    reference: str = ""
    origin: Vec3 = (0.0, 0.0, 0.0)
    closed: bool = False
    resolution: int = 24


@dataclass(frozen=True)
class InflationSpec:
    mode: InflationMode
    amount: float = 0.0
    minimum_amount: float = 0.0
    scale: Vec3 = (1.0, 1.0, 1.0)
    field_attribute: str = ""
    field_power: float = 1.0
    profile_width: float = 0.08
    profile_power: float = 0.65
    profile_segments: int = 9
    endpoint_taper: float = 0.16


@dataclass(frozen=True)
class MaterialSpec:
    preset: str = "GENERIC"
    shape_retention: float = 0.5
    volume_retention: float = 0.9


@dataclass(frozen=True)
class RelaxationSpec:
    sagginess: float = 0.35
    gravity: Vec3 = (0.0, 0.0, -1.0)
    sag_limit: float = 0.0


@dataclass(frozen=True)
class AttachmentSpec:
    target_kind: TargetKind = TargetKind.NONE
    target_id: str = ""
    target_surface: TargetSurface = TargetSurface.AUTO
    mode: AttachmentMode = AttachmentMode.FREE
    strength: float = 0.0
    mask_attribute: str = ""
    normal_offset: float = 0.0


@dataclass(frozen=True)
class SolverSpec:
    mode: SolverMode = SolverMode.NONE
    iterations: int = 24
    constraint_passes: int = 2
    tolerance: float = 1e-5


@dataclass(frozen=True)
class SoftTissueVCPModel:
    id: str
    name: str
    preset: TissuePreset
    boundary: BoundaryMode
    base: BaseObjectSpec
    inflation: InflationSpec
    material: MaterialSpec = field(default_factory=MaterialSpec)
    relaxation: RelaxationSpec = field(default_factory=RelaxationSpec)
    attachments: tuple[AttachmentSpec, ...] = ()
    solver: SolverSpec = field(default_factory=SolverSpec)
    schema_version: int = SCHEMA_VERSION


def model_to_dict(model):
    return asdict(model)


def validate_model(model):
    errors = _identity_errors(model)
    errors += _base_errors(model.base)
    errors += _inflation_errors(model.base, model.inflation)
    errors += _material_errors(model.material)
    errors += _relaxation_errors(model.relaxation)
    errors += _attachment_errors(model.attachments)
    errors += _solver_errors(model.solver)
    return tuple(errors)


def construction_mode_for_domain(domain):
    try:
        key = BaseDomain(str(getattr(domain, "value", domain)))
    except ValueError:
        return None
    return _DOMAIN_MODE.get(key)


def _identity_errors(model):
    errors = []
    if not str(model.id or "").strip() or not str(model.name or "").strip():
        errors.append("id and name are required")
    if int(model.schema_version) != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    return errors


def _base_errors(base):
    errors = []
    if base.domain != BaseDomain.POINT and not str(base.reference or ""):
        errors.append("curve and surface bases require a reference")
    if len(tuple(base.origin)) != 3 or int(base.resolution) < 3:
        errors.append("base origin or resolution is invalid")
    return errors


def _inflation_errors(base, inflation):
    errors = []
    if inflation.amount < 0.0 or not 0.0 <= inflation.minimum_amount <= inflation.amount:
        errors.append("inflation amount range is invalid")
    if len(tuple(inflation.scale)) != 3 or min(inflation.scale) <= 0.0:
        errors.append("inflation scale must contain three positive values")
    errors += _inflation_domain_errors(base.domain, inflation)
    return errors


def _inflation_domain_errors(domain, inflation):
    allowed = _DOMAIN_MODES.get(domain, set())
    errors = [] if inflation.mode in allowed else [f"{inflation.mode.value} is invalid for {domain.value}"]
    if inflation.field_power <= 0.0 or inflation.profile_power <= 0.0:
        errors.append("inflation field and profile powers must be positive")
    if inflation.profile_width <= 0.0 or inflation.profile_segments < 3:
        errors.append("profile width or segment count is invalid")
    return errors


def _material_errors(material):
    names = ("shape_retention", "volume_retention")
    return [_range_error(name) for name in names if not _unit_value(getattr(material, name))]


def _relaxation_errors(relaxation):
    errors = []
    if not _unit_value(relaxation.sagginess):
        errors.append(_range_error("sagginess"))
    if len(tuple(relaxation.gravity)) != 3 or relaxation.sag_limit < 0.0:
        errors.append("gravity or sag limit is invalid")
    return errors


def _attachment_errors(attachments):
    errors = []
    for item in attachments:
        errors += _one_attachment_errors(item)
    return errors


def _one_attachment_errors(item):
    errors = []
    if item.target_kind != TargetKind.NONE and not item.target_id:
        errors.append("attachment target_id is required")
    if item.target_surface not in _TARGET_SURFACES.get(item.target_kind, set()):
        errors.append("attachment target surface is invalid")
    if not _unit_value(item.strength):
        errors.append(_range_error("attachment strength"))
    return errors


def _solver_errors(solver):
    errors = []
    if int(solver.iterations) < 1 or int(solver.constraint_passes) < 1:
        errors.append("solver iterations and constraint passes must be positive")
    if float(solver.tolerance) <= 0.0:
        errors.append("solver tolerance must be positive")
    return errors


def _unit_value(value):
    return 0.0 <= float(value) <= 1.0


def _range_error(name):
    return f"{name} must be between 0 and 1"


_DOMAIN_MODE = {BaseDomain.POINT: InflationMode.RADIAL, BaseDomain.CURVE: InflationMode.PROFILE,
                BaseDomain.SURFACE: InflationMode.NORMAL}
_DOMAIN_MODES = {domain: {mode} for domain, mode in _DOMAIN_MODE.items()}
_TARGET_SURFACES = {
    TargetKind.NONE: {TargetSurface.AUTO},
    TargetKind.SCP: {TargetSurface.SCP_GEOMETRY},
}
