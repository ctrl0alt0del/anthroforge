from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class SurfaceTargetKind(str, Enum):
    NONE = "NONE"
    SCP = "SCP"
    MUSCLE = "MUSCLE"


class SurfaceRole(str, Enum):
    AUTO = "AUTO"
    SCP_GEOMETRY = "SCP_GEOMETRY"
    MUSCLE_BASE = "MUSCLE_BASE"
    MUSCLE_INFL = "MUSCLE_INFL"


@dataclass(frozen=True)
class SurfaceTargetRef:
    kind: SurfaceTargetKind = SurfaceTargetKind.NONE
    entity_id: str = ""
    surface: SurfaceRole = SurfaceRole.AUTO


@dataclass(frozen=True)
class SurfaceTargetDescriptor:
    kind: SurfaceTargetKind
    roles: tuple[SurfaceRole, ...]
    dependency_entity_type: str


@dataclass(frozen=True)
class AttachmentRegionSpec:
    mode: str = "SOFT"
    strength: float = 0.5
    feather: float = 0.0
    mask_attribute: str = "ALL"
    normal_offset: float = 0.0


@dataclass(frozen=True)
class SurfaceBinding:
    raw: str
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class SurfaceBindingEnvelope:
    target: SurfaceTargetRef
    topology_signature: str
    bindings: tuple = ()
    rest_topology_signature: str = ""
    version: int = 3


TARGET_CONTRACTS = MappingProxyType({
    SurfaceTargetKind.NONE: SurfaceTargetDescriptor(SurfaceTargetKind.NONE, (SurfaceRole.AUTO,), ""),
    SurfaceTargetKind.SCP: SurfaceTargetDescriptor(SurfaceTargetKind.SCP, (SurfaceRole.SCP_GEOMETRY,), "SCP"),
    SurfaceTargetKind.MUSCLE: SurfaceTargetDescriptor(
        SurfaceTargetKind.MUSCLE, (SurfaceRole.MUSCLE_BASE, SurfaceRole.MUSCLE_INFL), "MUSCLE"),
})


def target_ref(kind="NONE", entity_id="", surface="AUTO"):
    return SurfaceTargetRef(SurfaceTargetKind(str(kind)), str(entity_id or ""), SurfaceRole(str(surface)))


def target_ref_errors(ref):
    descriptor = TARGET_CONTRACTS.get(ref.kind)
    errors = [] if descriptor else ["Unknown surface target type."]
    if descriptor and ref.surface not in descriptor.roles:
        errors.append(f"{ref.surface.value} is invalid for {ref.kind.value}.")
    if ref.kind != SurfaceTargetKind.NONE and not ref.entity_id:
        errors.append("Surface target ID is required.")
    return tuple(errors)


def effective_tissue_target(tissue):
    if int(getattr(tissue, "schema_version", 1)) < 2:
        return _legacy_tissue_target(tissue)
    return target_ref(getattr(tissue, "attachment_target_type", "NONE"),
                      getattr(tissue, "attachment_target_id", ""),
                      getattr(tissue, "attachment_target_surface", "AUTO"))


def _legacy_tissue_target(tissue):
    entity_id = str(getattr(tissue, "host_scp_id", "") or "")
    return target_ref("SCP", entity_id, "SCP_GEOMETRY") if entity_id else target_ref()


def target_payload(ref):
    return {"type": ref.kind.value, "id": ref.entity_id, "surface": ref.surface.value}


def target_from_payload(value):
    data = dict(value or {})
    return target_ref(data.get("type", "NONE"), data.get("id", ""), data.get("surface", "AUTO"))


def target_dependency(ref):
    descriptor = TARGET_CONTRACTS.get(ref.kind)
    return "" if descriptor is None else descriptor.dependency_entity_type
