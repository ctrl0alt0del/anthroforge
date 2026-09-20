"""Guardable output-domain edits reuse native capture, evaluation and publication."""
from ..use_cases import muscle_profile as profiles
from ...core.vcp.muscle_output_domain import native_values, normalize
from ...core.vcp.muscle_numeric import execute_muscle_batch
from ...core.authoring.native_assignment import assign_checked
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates
import numpy as np


def candidate(target, configuration):
    if not target.current or target.muscle is None:
        raise ValueError('DOMAIN_BASE_NOT_CURRENT')
    value = profiles._candidate(target.muscle, profiles.mode_configuration(target.muscle, _mode(target.muscle)))
    for key, item in native_values(configuration).items():
        setattr(value, key, np.asarray(item, np.float32).tolist() if key in ('output_domain_origin', 'output_domain_normal') else item)
    return value


def _mode(muscle):
    return dict(CTRL_POINT='control_point', DISTRIBUTED='distributed', SECTION_PROFILE='section_profile')[muscle.inflation_mode]


def preview(target, configuration):
    value = candidate(target, normalize(configuration))
    request = profiles._preview_request(target, value, value.inflation_mode == 'CTRL_POINT' and not value.inflation_ctrl_initialized)
    batch = execute_muscle_batch((request,))
    if batch.results[0].error:
        raise ValueError(batch.results[0].error)
    if not len(batch.results[0].faces):
        raise ValueError('DOMAIN_EMPTY: cut excludes the complete muscle')
    return request, batch


def write_configuration(muscle, configuration):
    with suppress_vcp_prop_updates():
        for key, value in native_values(configuration).items():
            assign_checked(muscle, key, value)


def configure(root, scene, muscle_id, configuration):
    target, _ = profiles.inspect(root, scene, muscle_id)
    request, batch = preview(target, configuration)
    with profiles.transaction(root, scene, target.muscle):
        write_configuration(target.muscle, configuration)
        profiles.publish(root, scene, target.muscle, request, batch)
    return normalize(configuration)
