"""Detached static parameter/profile variants; never joint trajectories."""
from copy import deepcopy
from .errors import require
from .references import lookup


def apply_variant(document, scenario):
    value = deepcopy(document)
    profile = lookup(document, scenario['profile'])
    evaluation = lookup(document, scenario['evaluation_profile'])
    require(evaluation['purpose'] == 'static_avatar', 'STATIC_PROFILE_REQUIRED')
    require(profile['reference_pose'] == evaluation['reference_pose'], 'REFERENCE_POSE_MISMATCH')
    for instance in value.get('instances', {}).values():
        old = instance['profile']
        instance['profile'] = scenario['profile']
        instance['bindings'] = {k: scenario['profile']+r[len(old):] if r.startswith(old+'/') else r for k, r in instance['bindings'].items()}
    for path, number in scenario['parameter_overrides'].items():
        name, parameter = path.rsplit('.', 1)
        require(name in value.get('instances', {}), 'VARIANT_INSTANCE_UNDEFINED')
        value['instances'][name]['parameters'][parameter] = number
    return value
