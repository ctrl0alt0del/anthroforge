from dataclasses import dataclass
from typing import Protocol

from ..scp_runtime.common import find_geometry_mesh_scp_obj
from ..vcp.surface_topology import signature as connectivity_signature
from ..vcp.surface_target import SurfaceRole, SurfaceTargetKind, SurfaceTargetRef, target_ref_errors
from .muscle_sync_helpers import resolve_muscle_surface


@dataclass(frozen=True)
class ResolvedSurfaceTarget:
    reference: SurfaceTargetRef
    mesh_object: object
    topology_signature: str
    generation: tuple = ()
    readiness: str = 'CURRENT'
    reason: str = ''


class SurfaceTargetProvider(Protocol):
    kind: SurfaceTargetKind

    def resolve(self, root, scene, target_ref, runtime):
        ...


class SCPSurfaceTargetProvider:
    kind = SurfaceTargetKind.SCP

    def resolve(self, root, scene, target_ref, runtime):
        obj = find_geometry_mesh_scp_obj(scene, root.name, target_ref.entity_id)
        if target_ref.instance == 'mirror': obj = _scp_mirror(root, scene, target_ref.entity_id)
        return _resolved_target(target_ref, obj, runtime, scene, "SCP geometry")


class MuscleSurfaceTargetProvider:
    kind = SurfaceTargetKind.MUSCLE

    def resolve(self, root, scene, target_ref, runtime):
        role = _muscle_role(target_ref.surface)
        obj = _muscle_object(root, scene, target_ref, role)
        from dataclasses import replace
        from .surface_publication import state
        result = _resolved_target(target_ref, obj, runtime, scene, f"Muscle {role}")
        status, reason = state(root, scene, target_ref, obj)
        return replace(result, readiness=status, reason=reason)


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
    if obj.type != "MESH":
        raise ValueError(f"{label} is not a mesh target.")
    signature = connectivity_signature(obj, runtime, scene)
    if not signature:
        raise ValueError(f"{label} evaluated surface is unavailable.")
    from .surface_publication import generation
    return ResolvedSurfaceTarget(reference, obj, signature, generation(obj))


def _muscle_object(root, scene, ref, role):
    if not any(m.id == ref.entity_id for m in root.af_vcp_system.muscles): return None
    found = [o for o in scene.objects if o.get('af_root_name') == root.name
             and o.get('af_muscle_proxy') and bool(o.get('af_muscle_mirror_proxy')) == (ref.instance == 'mirror')
             and o.get('af_source_muscle_id' if ref.instance == 'mirror' else 'af_muscle_id') == ref.entity_id
             and o.get('af_muscle_surface') == role]
    if len(found) > 1: raise ValueError('Ambiguous muscle surface identity.')
    return found[0] if found else None


def _scp_mirror(root, scene, identity):
    found = [o for o in scene.objects if o.get('af_root_name') == root.name and o.get('af_scp_geometry')
             and o.get('af_scp_mirror') and o.get('af_source_scp_id') == identity]
    if len(found) > 1: raise ValueError('Ambiguous mirrored SCP surface.')
    return found[0] if found else None
