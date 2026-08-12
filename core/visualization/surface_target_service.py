from dataclasses import dataclass
from typing import Protocol

from ..scp_runtime.common import find_geometry_mesh_scp_obj
from ..vcp.attachment_backend import surface_binding_topology
from ..vcp.surface_target import SurfaceRole, SurfaceTargetKind, SurfaceTargetRef, target_ref_errors
from .muscle_sync_helpers import resolve_muscle_surface


@dataclass(frozen=True)
class ResolvedSurfaceTarget:
    reference: SurfaceTargetRef
    mesh_object: object
    topology_signature: str


class SurfaceTargetProvider(Protocol):
    kind: SurfaceTargetKind

    def resolve(self, root, scene, target_ref, runtime):
        ...


class SCPSurfaceTargetProvider:
    kind = SurfaceTargetKind.SCP

    def resolve(self, root, scene, target_ref, runtime):
        obj = find_geometry_mesh_scp_obj(scene, root.name, target_ref.entity_id)
        return _resolved_target(target_ref, obj, runtime, scene, "SCP geometry")


class MuscleSurfaceTargetProvider:
    kind = SurfaceTargetKind.MUSCLE

    def resolve(self, root, scene, target_ref, runtime):
        role = _muscle_role(target_ref.surface)
        obj = resolve_muscle_surface(root, target_ref.entity_id, role, scene)
        return _resolved_target(target_ref, obj, runtime, scene, f"Muscle {role}")


class SurfaceTargetService:
    def __init__(self, providers):
        self._providers = {provider.kind: provider for provider in tuple(providers)}

    def resolve(self, root, scene, target_ref, runtime=None):
        errors = target_ref_errors(target_ref)
        if errors:
            raise ValueError(" ".join(errors))
        if target_ref.kind == SurfaceTargetKind.NONE:
            return None
        provider = self._providers.get(target_ref.kind)
        if provider is None:
            raise ValueError(f"No provider for {target_ref.kind.value} surface targets.")
        return provider.resolve(root, scene, target_ref, runtime)


def default_surface_target_service():
    return SurfaceTargetService((SCPSurfaceTargetProvider(), MuscleSurfaceTargetProvider()))


def _muscle_role(surface):
    roles = {SurfaceRole.MUSCLE_BASE: "BASE", SurfaceRole.MUSCLE_INFL: "INFL"}
    if surface not in roles:
        raise ValueError("Muscle target requires an explicit BASE or INFL surface.")
    return roles[surface]


def _resolved_target(reference, obj, runtime, scene, label):
    if obj is None:
        raise ValueError(f"{label} target is missing.")
    if obj.type != "MESH" or obj.get("af_muscle_mirror_proxy"):
        raise ValueError(f"{label} is not an original mesh target.")
    signature = surface_binding_topology(obj, runtime, scene)
    if not signature:
        raise ValueError(f"{label} evaluated surface is unavailable.")
    return ResolvedSurfaceTarget(reference, obj, signature)
