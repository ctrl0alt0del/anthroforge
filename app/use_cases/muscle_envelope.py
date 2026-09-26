"""One inspect/preview/configure path for native envelope UI and authoring."""
from ...core.authoring.envelope_config import normalize, configuration, side_values
from ...core.authoring.codec import digest
from ...core.vcp.muscle_numeric import execute_muscle_batch
from ...core.visualization.muscle_profile_capture import capture_target
from ...core.visualization.muscle_profile_publish import transaction, publish
from ...core.visualization.muscle_envelope_storage import parts
from ...core.vcp.prop_update_guard import suppress_vcp_prop_updates


def inspect(root, scene, muscle_id):
    target = capture_target(root, scene, muscle_id)
    validate_version(target.muscle)
    config = configuration(root, target.muscle)
    eligible = target.current and (target.assembly is not None or target.eligible)
    return target, dict(muscle_id=muscle_id, source_id=target.source.id, base_revision=target.base_revision,
        configuration=config, configuration_revision=digest(config), current=target.current, eligible=eligible,
        reasons=[] if eligible else list(target.reasons), schema='muscle_inflation_envelope.v1', retained_banks=retained(root, target.muscle), **_details(target))


def preview(target, value):
    validate_version(target.muscle)
    value = normalize(value)
    if not target.current or (target.assembly is None and not target.eligible):
        raise ValueError('; '.join(target.reasons))
    request = _request(target, value)
    batch = execute_muscle_batch((request,))
    if batch.results[0].error: raise ValueError(batch.results[0].error)
    return value, request, batch


def _request(target, value):
    from ...core.visualization.muscle_numeric_runtime import _make_request, _make_branched_request
    muscle = target.muscle
    owners = parts(muscle.id_data, muscle); records = {p['part_id']: p for p in value['parts']}
    if set(records) != {key for key, _ in owners}: raise ValueError('ENVELOPE_PART_MISMATCH')
    request = _make_branched_request(muscle, target.source, target.assembly, False) if target.assembly else _make_request(muscle, target.payload, envelope=False)
    from ...core.authoring.envelope_numeric import configured
    return configured(request, value, tuple(key for key, _ in owners))


def write(root, muscle, value):
    owners = dict(parts(root, muscle))
    with suppress_vcp_prop_updates():
        for record in value['parts']:
            owner = owners[record['part_id']]
            for settings, side in ((owner, record['a']), (owner.inflation_secondary, record['b'])):
                for key, item in side_values(side).items(): setattr(settings, key, item)
            owner.inflation_secondary.id = muscle.id; owner.inflation_secondary.initialized = True
        muscle.envelope_version = 1; muscle.envelope_enabled = value['enabled']
        muscle.envelope_reverse = value['reverse_sides']
        muscle.envelope_sides = 'BOTH_SIDES' if value['sides'] == 'both' else 'ONE_SIDE'


def configure(root, scene, muscle_id, value):
    target = capture_target(root, scene, muscle_id)
    value, request, batch = preview(target, value)
    with transaction(root, scene, target.muscle):
        write(root, target.muscle, value)
        publish(root, scene, target.muscle, request, batch)
    return value


def validate_version(muscle):
    if muscle.envelope_version not in (0, 1): raise ValueError('ENVELOPE_VERSION_UNSUPPORTED')


def retained(root, muscle):
    from ...core.visualization.muscle_envelope_storage import fields, snapshot, _plain
    return {key: dict(a={name: _plain(getattr(owner, name)) for name in fields(owner)}, b=snapshot(owner))
            for key, owner in parts(root, muscle)}


def copy_banks(root, muscle, action):
    from ...core.visualization.muscle_envelope_storage import selected_settings, copy_settings
    _, key, _ = selected_settings(root, muscle)
    with suppress_vcp_prop_updates():
        for identity, owner in parts(root, muscle):
            if 'ALL' not in action and identity != (key or 'main'): continue
            a, b = owner, owner.inflation_secondary
            copy_settings(a, b) if action.endswith('A_B') else copy_settings(b, a)
            b.id, b.initialized = muscle.id, True


def _details(target):
    from ...core.authoring.codec import decode
    modes = ['control_point', 'distributed'] + ([] if target.assembly else ['section_profile'])
    return dict(supported_modes=modes, depth_convention='distance_from_unchanged_base',
                diagnostics=decode(target.muscle.get('_af_rt_envelope_diagnostics', '{}')),
                diagnostics_scope='last_published_geometry; inspect eligibility/current before use')
