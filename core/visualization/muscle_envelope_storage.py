"""Single authoritative A/B settings storage and numeric capture adapters."""
from dataclasses import replace
from ..vcp.prop_update_guard import suppress_vcp_prop_updates


def parts(root, muscle):
    from .branch_control import branch_surface
    surface = branch_surface(root, muscle)
    return (('main', muscle), *((b.id, b.settings) for b in surface.branches)) if surface else (('main', muscle),)


def fields(settings):
    return tuple(p.identifier for p in settings.bl_rna.properties if
                 p.identifier.startswith(('inflation_', 'section_')) and p.type not in ('POINTER', 'COLLECTION'))


def copy_settings(source, destination):
    for key in fields(source):
        setattr(destination, key, getattr(source, key))
    destination.id = source.id


def initialize(muscle):
    if muscle.envelope_version not in (0, 1): raise ValueError('ENVELOPE_VERSION_UNSUPPORTED')
    with suppress_vcp_prop_updates():
        for _, owner in parts(muscle.id_data, muscle):
            if not owner.inflation_secondary.initialized:
                copy_settings(owner, owner.inflation_secondary)
                owner.inflation_secondary.initialized = True
        muscle.envelope_version = 1


def selected_settings(root, muscle):
    from .branch_control import selected_part
    settings, key, index = selected_part(root, muscle)
    if muscle.envelope_sides == 'BOTH_SIDES' and muscle.envelope_edit_side == 'B':
        settings = settings.inflation_secondary
    return settings, key, index


def attach(request, muscle):
    both = getattr(muscle, 'envelope_sides', 'ONE_SIDE') == 'BOTH_SIDES'
    reverse = bool(getattr(muscle, 'envelope_reverse', False))
    if not both:
        if getattr(muscle, 'envelope_version', 0) == 1 and not muscle.envelope_enabled:
            request = _disabled(request)
        if not reverse: return request
        return replace(request, assembly=replace(request.assembly, flip=not request.assembly.flip)) if hasattr(request, 'assembly') else replace(request, spec=replace(request.spec, flip_normals=not request.spec.flip_normals))
    from ..vcp.muscle_envelope import MuscleEnvelopeSpec
    owners = parts(muscle.id_data, muscle)
    secondary = tuple(_secondary_spec(owner, spec) for (_, owner), spec in zip(owners,
        request.part_specs if hasattr(request, 'assembly') else (request.spec,)))
    envelope = MuscleEnvelopeSpec(secondary, muscle.envelope_enabled, reverse, muscle.envelope_version)
    return replace(request, envelope=envelope)


def _secondary_spec(owner, primary):
    from .muscle_numeric_runtime import _numeric_spec
    side = owner.inflation_secondary
    if not side.initialized: raise ValueError('ENVELOPE_SECONDARY_UNINITIALIZED')
    spec = _numeric_spec(side, owner, primary.target_count, primary.densify, primary.closed_u,
                         side.inflation_mode == 'CTRL_POINT' and not side.inflation_ctrl_initialized)
    return replace(spec, preserve_samples=primary.preserve_samples, closed_v=primary.closed_v,
        close_across_fibers=primary.close_across_fibers, topology_flip_normals=primary.topology_flip_normals)


def owner_for(root, settings):
    pointer = settings.as_pointer()
    for muscle in root.af_vcp_system.muscles:
        for _, part in parts(root, muscle):
            if pointer in (part.as_pointer(), part.inflation_secondary.as_pointer()): return muscle
    return None


def snapshot(settings):
    side = settings.inflation_secondary
    return dict(initialized=side.initialized, **{key: _plain(getattr(side, key)) for key in fields(side)})


def _plain(value):
    return list(value) if not isinstance(value, (str, int, float, bool)) else value


def restore(settings, values):
    with suppress_vcp_prop_updates():
        for key, value in values.items(): setattr(settings.inflation_secondary, key, value)
        settings.inflation_secondary.id = settings.id


def _disabled(request):
    if hasattr(request, 'assembly'):
        return replace(request, part_specs=tuple(replace(s, inflation_enabled=False) for s in request.part_specs))
    return replace(request, spec=replace(request.spec, inflation_enabled=False))
