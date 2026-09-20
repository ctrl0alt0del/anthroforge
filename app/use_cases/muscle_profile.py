"""Shared native profile commands; UI and authoring use identical candidates."""
from dataclasses import replace
from math import isfinite
try:
    from ...core.authoring.profile_config import current_configuration, native_values, normalize, wire
    from ...core.vcp.muscle_section_profile import profile_from_muscle, reset_profile, scale_profile
    from ...core.vcp.muscle_numeric import execute_muscle_batch
    from ...core.visualization.muscle_profile_capture import capture_target, default_muscle
    from ...core.visualization.muscle_numeric_runtime import _make_request
    from ...core.visualization.muscle_profile_publish import transaction, publish
    from ...core.authoring.native_assignment import assign_checked
    from ...core.authoring.legacy_config import legacy_state
    from ...core.visualization.muscle_legacy_profile import configuration_state, oriented_request, publish_side
    from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
except ImportError:
    from core.authoring.profile_config import current_configuration, native_values, normalize, wire
    from core.vcp.muscle_section_profile import profile_from_muscle, reset_profile, scale_profile
    from core.vcp.muscle_numeric import execute_muscle_batch
    from core.visualization.muscle_profile_capture import capture_target, default_muscle
    from core.visualization.muscle_numeric_runtime import _make_request
    from core.visualization.muscle_profile_publish import transaction, publish
    from core.authoring.native_assignment import assign_checked
    from core.authoring.legacy_config import legacy_state
    from core.visualization.muscle_legacy_profile import configuration_state, oriented_request, publish_side
    from core.vcp.prop_update_guard import suppress_vcp_prop_updates


def inspect(root, scene, muscle_id="", surface_id=""):
    from ...core.vcp.muscle_output_domain import configuration as domain_configuration
    target = capture_target(root, scene, muscle_id, surface_id)
    state, configuration, error = _profile_state(target.muscle)
    return target, dict(muscle_id=muscle_id or None, source_id=target.source.id, base_revision=target.base_revision,
        eligible=target.eligible, current=target.current, reasons=list(target.reasons), chart=list(target.chart),
        configuration=configuration, legacy_configuration=configuration_state(target), profile_state=state, profile_error=error,
        initialization_proposal=_proposal(target.muscle), ownership=_ownership(target.muscle), native_state=_native_state(target.muscle),
        output_domain=domain_configuration(target.muscle))


def _profile_state(muscle):
    if muscle is None:
        return "surface_only", None, ""
    try:
        configuration = current_configuration(muscle)
        state = "uninitialized" if muscle.section_profile_version == 0 else "valid"
        return state, configuration, ""
    except ValueError as error:
        state = "uninitialized" if muscle.section_profile_version == 0 else "invalid"
        return ("unsupported_version" if muscle.section_profile_version not in (0, 1) else state), None, str(error)


def _proposal(muscle):
    amount = float(muscle.inflation_max_value) if muscle else .05
    try:
        return wire(reset_profile(amount), muscle.inflation_enabled if muscle else True, muscle.flip_normals if muscle else False)
    except ValueError:
        return wire(reset_profile(.05))


def _ownership(muscle):
    if muscle is None:
        return None
    return {key: str(muscle[key]) for key in muscle.keys() if key.startswith("af_authoring") and "receipt" not in key and "creation" not in key}


def preview(target, configuration):
    configuration = normalize(configuration)
    _validate_target(target, configuration)
    candidate = _candidate(target.muscle, configuration)
    initialize = candidate.inflation_mode == "CTRL_POINT" and not candidate.inflation_ctrl_initialized
    request = oriented_request(_preview_request(target, candidate, initialize), target, configuration)
    batch = execute_muscle_batch((request,))
    if batch.results[0].error:
        raise ValueError(batch.results[0].error)
    return configuration, request, batch


def _preview_request(target, candidate, initialize):
    if target.assembly is not None:
        from ...core.visualization.muscle_numeric_runtime import _make_branched_request
        return _make_branched_request(candidate, target.source, target.assembly)
    return _make_request(candidate, target.payload, initialize)


def _validate_target(target, configuration):
    if target.assembly is not None and 'flip_normals' in configuration.get('native', {}):
        raise ValueError('PROFILE_SIDE_UNSUPPORTED: use surface_flip_normals for the whole branched assembly')
    if target.eligible:
        return
    if target.muscle is not None and configuration['mode'] != 'section_profile' and target.current:
        return
    raise ValueError('; '.join(target.reasons))


def _candidate(muscle, configuration):
    candidate = default_muscle()
    candidate.inflation_enabled = True
    if muscle is not None:
        for key in tuple(vars(candidate)):
            if key != "get" and hasattr(muscle, key):
                setattr(candidate, key, getattr(muscle, key))
    for key, value in native_values(configuration).items():
        setattr(candidate, key, value)
    candidate.get = lambda key, default=None: getattr(candidate, key, default)
    return candidate


def write_configuration(muscle, configuration):
    with suppress_vcp_prop_updates():
        for key, value in native_values(configuration).items():
            assign_checked(muscle, key, value)


def configure(root, scene, muscle_id, configuration):
    target = capture_target(root, scene, muscle_id)
    configuration, request, batch = preview(target, configuration)
    with transaction(root, scene, target.muscle):
        write_configuration(target.muscle, configuration)
        publish_side(root, scene, target, configuration)
        publish(root, scene, target.muscle, request, batch)
    return configuration


def mode_configuration(muscle, mode):
    if mode in ("control_point", "distributed"):
        return dict(mode=mode)
    if mode != "section_profile":
        raise ValueError("PROFILE_MODE_UNSUPPORTED")
    spec = reset_profile(muscle.inflation_max_value) if muscle.section_profile_version == 0 else profile_from_muscle(muscle)
    return wire(spec, muscle.inflation_enabled, muscle.flip_normals)


def action_configuration(muscle, action, value=1):
    if action == "reset":
        return wire(reset_profile(value), muscle.inflation_enabled, muscle.flip_normals)
    spec = profile_from_muscle(muscle)
    if action == "scale":
        spec = scale_profile(spec, value)
    return wire(spec, muscle.inflation_enabled, not muscle.flip_normals if action == "side" else muscle.flip_normals)


def _native_state(muscle):
    if muscle is None:
        return None
    return dict(mode=muscle.inflation_mode, version=muscle.section_profile_version,
        depths=[_finite_value(v) for v in muscle.section_depths], peaks=[_finite_value(v) for v in muscle.section_peaks],
        roundness=_finite_value(muscle.section_roundness),
        direction=muscle.section_direction, enabled=muscle.inflation_enabled, flip_normals=muscle.flip_normals, legacy=legacy_state(muscle))


def _finite_value(value):
    return value if isfinite(value) else str(value)
