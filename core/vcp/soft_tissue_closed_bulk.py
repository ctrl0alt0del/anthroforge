from dataclasses import dataclass, field

from .soft_tissue_model import (
    AttachmentSpec, BaseDomain, BaseObjectSpec, BoundaryMode, InflationMode,
    InflationSpec, MaterialSpec, RelaxationSpec, SoftTissueVCPModel,
    SolverMode, SolverSpec, TargetKind, TissuePreset, Vec3, validate_model,
)


LEGACY_SAG_MAX = 10.0


@dataclass(frozen=True)
class LegacyBlobSpec:
    id: str
    name: str
    center: Vec3 = (0.0, 0.0, 0.0)
    radius: float = 0.2
    shape: str = "SPHERE"
    axis_scale: Vec3 = (1.0, 1.0, 1.0)
    resolution: int = 24
    gravity: Vec3 = (0.0, 0.0, -1.0)
    sag_strength: float = 0.35
    sag_limit: float = 0.35
    stiffness: float = 0.25
    iterations: int = 20
    attachment: AttachmentSpec = field(default_factory=AttachmentSpec)


def closed_bulk_model_from_legacy(spec):
    _raise_errors(validate_legacy_blob_spec(spec))
    model = SoftTissueVCPModel(
        spec.id, spec.name, TissuePreset.CLOSED_BULK, BoundaryMode.CLOSED, _base(spec),
        _inflation(spec), _material(spec), _relaxation(spec), _attachments(spec),
        solver=_solver(spec),
    )
    _raise_errors(validate_model(model))
    return model


def legacy_spec_from_closed_bulk(model):
    _raise_errors(validate_model(model) + _closed_bulk_errors(model))
    scale = tuple(float(value) for value in model.inflation.scale)
    attachment = model.attachments[0] if model.attachments else AttachmentSpec()
    return LegacyBlobSpec(
        model.id, model.name, tuple(model.base.origin), float(model.inflation.amount),
        _shape_from_scale(scale), scale, int(model.base.resolution),
        tuple(model.relaxation.gravity), model.relaxation.sagginess * LEGACY_SAG_MAX,
        float(model.relaxation.sag_limit), float(model.material.shape_retention),
        int(model.solver.iterations), attachment,
    )


def validate_legacy_blob_spec(spec):
    errors = []
    if not str(spec.id or "").strip() or not str(spec.name or "").strip():
        errors.append("legacy blob id and name are required")
    if spec.shape not in {"SPHERE", "ELLIPSOID"}:
        errors.append("legacy blob shape must be SPHERE or ELLIPSOID")
    if spec.radius <= 0.0 or len(spec.axis_scale) != 3 or min(spec.axis_scale) <= 0.0:
        errors.append("legacy blob radius and axis scale must be positive")
    if not 8 <= int(spec.resolution) <= 128 or int(spec.iterations) < 1:
        errors.append("legacy blob resolution or iteration count is invalid")
    if not 0.0 <= spec.sag_strength <= LEGACY_SAG_MAX or spec.sag_limit < 0.0:
        errors.append("legacy blob sag parameters are invalid")
    if not 0.0 <= spec.stiffness <= 1.0:
        errors.append("legacy blob stiffness must be between zero and one")
    return tuple(errors)


def _closed_bulk_errors(model):
    errors = []
    if model.preset != TissuePreset.CLOSED_BULK or model.boundary != BoundaryMode.CLOSED:
        errors.append("closed bulk requires CLOSED_BULK preset and CLOSED boundary")
    if model.base.domain != BaseDomain.POINT:
        errors.append("closed bulk migration requires a point base")
    if model.inflation.mode != InflationMode.RADIAL:
        errors.append("closed bulk migration requires radial inflation")
    if len(model.attachments) > 1:
        errors.append("legacy blob migration supports one attachment target")
    return tuple(errors)


def _base(spec):
    return BaseObjectSpec(BaseDomain.POINT, origin=tuple(spec.center), resolution=spec.resolution)


def _inflation(spec):
    scale = (1.0, 1.0, 1.0) if spec.shape == "SPHERE" else tuple(spec.axis_scale)
    return InflationSpec(InflationMode.RADIAL, spec.radius, scale=scale)


def _material(spec):
    return MaterialSpec("ADIPOSE", shape_retention=spec.stiffness, volume_retention=0.9)


def _relaxation(spec):
    return RelaxationSpec(spec.sag_strength / LEGACY_SAG_MAX, tuple(spec.gravity), spec.sag_limit)


def _attachments(spec):
    return () if spec.attachment.target_kind == TargetKind.NONE else (spec.attachment,)


def _solver(spec):
    mode = SolverMode.GEOMETRIC if spec.sag_strength > 0.0 else SolverMode.NONE
    return SolverSpec(mode, spec.iterations, 1, 1.0e-6)


def _shape_from_scale(scale):
    return "SPHERE" if all(abs(value - 1.0) <= 1.0e-12 for value in scale) else "ELLIPSOID"


def _raise_errors(errors):
    if errors:
        raise ValueError("; ".join(errors))
