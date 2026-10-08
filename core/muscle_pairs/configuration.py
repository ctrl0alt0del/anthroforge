"""Persist only settings and explicit anatomical groups, never detection geometry."""
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
import json
import math
from .model import DetectionSettings
from ..authoring.codec import digest

KEY = 'af_pair_detection_configuration'
DEFAULT = dict(automatic=True, search_distance=.05, displacement=.5, stacking=True,
               clearance=0., smoothing_radius=.5, smoothing_strength=.8, exclusions=[],
               blend_distance=1., preservation_weight=100., smoothing_max_adjustment=4.)


def read(root):
    from ..muscle_relationships import store, migration
    value = json.loads(root.get(KEY, '{}'))
    if store.KEY in root: value['exclusions'] = migration.exclusions(store.read(root))
    return dict(DEFAULT, **value)


def settings(root):
    return from_values(read(root))


def from_values(value):
    from ..muscle_stacking.model import StackingSettings
    stack = StackingSettings(value['stacking'], value['clearance'], value['smoothing_radius'],
        value['smoothing_strength'], tuple(tuple(tuple(k) for k in pair) for pair in value['exclusions']),
        value['blend_distance'], value['preservation_weight'], value['smoothing_max_adjustment'])
    return DetectionSettings(search_distance=value['search_distance'], displacement=value['displacement'], stacking=stack)


def inspect(root):
    from ..muscle_relationships import store
    from ..muscle_relationships.changes import configuration_intent
    groups = {m.id: str(m.get('af_pair_group_id', '')) for m in root.af_vcp_system.muscles}
    value = dict(settings=read(root), groups=groups)
    signature = dict(value, relationships=configuration_intent(store.read(root)))
    return dict(value, configuration_revision=digest(signature), numerical_limits=asdict(settings(root)))


def validate(root, change):
    if set(change) - (set(DEFAULT) | {'groups'}): raise ValueError('PAIR_SETTING_UNKNOWN')
    value = dict(read(root), **{k: v for k, v in change.items() if k != 'groups'})
    if any(type(value[k]) is not bool for k in ('automatic', 'stacking')): raise ValueError('PAIR_AUTOMATIC_INVALID')
    for key in ('search_distance', 'displacement', 'clearance', 'smoothing_radius', 'smoothing_strength', 'blend_distance', 'preservation_weight', 'smoothing_max_adjustment'):
        if isinstance(value[key], bool) or not isinstance(value[key], (int, float)) or not math.isfinite(value[key]) or value[key] < 0:
            raise ValueError('PAIR_DISTANCE_INVALID')
    if value['preservation_weight'] < 1: raise ValueError('STACK_PRESERVATION_WEIGHT_INVALID')
    groups = change.get('groups', {}); known = {m.id for m in root.af_vcp_system.muscles}
    if not isinstance(groups, dict) or set(groups)-known: raise ValueError('PAIR_GROUP_TARGET_INVALID')
    if any(not isinstance(v, str) or len(v) > 256 for v in groups.values()): raise ValueError('PAIR_GROUP_INVALID')
    if 'exclusions' in change: validate_exclusions(value['exclusions'], known)
    return value, groups


def validate_exclusions(values, known):
    if not isinstance(values, (list, tuple)): raise ValueError('STACK_EXCLUSIONS_INVALID')
    for pair in values:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2: raise ValueError('STACK_EXCLUSION_PAIR')
        for key in pair:
            if not isinstance(key, (list, tuple)) or len(key) != 3: raise ValueError('STACK_EXCLUSION_KEY')
            if key[0] not in known or key[1] not in ('source', 'mirror') or key[2] not in ('A', 'B'):
                raise ValueError('STACK_EXCLUSION_TARGET')


@contextmanager
def transaction(root, change):
    from ..muscle_relationships import store, migration
    value, groups = validate(root, change); old = root.get(KEY)
    muscles = {m.id: m for m in root.af_vcp_system.muscles}; prior = {k: muscles[k].get('af_pair_group_id') for k in groups}
    try:
        with migration.rollback(root):
            document = migration.ensure(root); updated = migration.with_exclusions(document, value.pop('exclusions'))
            with store.transaction(root, updated, document['revision']) if 'exclusions' in change else nullcontext():
                root[KEY] = json.dumps(value, sort_keys=True)
                for key, group in groups.items(): muscles[key]['af_pair_group_id'] = group
                yield inspect(root)
    except BaseException:
        restore(root, KEY, old)
        for key, group in prior.items(): restore(muscles[key], 'af_pair_group_id', group)
        raise


def restore(owner, key, value):
    if value is None:
        if key in owner: del owner[key]
    else: owner[key] = value
