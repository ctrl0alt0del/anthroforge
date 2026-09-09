"""Lower anatomical intent into the shared native compiler's input format."""
from copy import deepcopy
from .codec import digest
from .errors import require
from .validation import document as validate_document
from .references import lookup
from .substrate import binding, frame, frame_spec, control, guide_position, coordinates
from .strategies import construction_strategies


def identity(reference):
    return 'r_'+digest(reference)[:20]


def evidence(value):
    return dict(basis='designer_authored' if value['basis'] == 'designer_authored' else value['basis'], sources=[identity(r) for r in value['sources']], note=value['note'])


def empty(document, pose):
    result = dict(dsl='anthroforge.authoring', version='0.3.0', document_id=document['document_id'], revision=document['revision'], context=dict(reference_pose=pose, units=dict(mode='relative'), scope='Static avatar authoring; anatomical review tracked separately.', example_only=True))
    result['$schema'] = 'urn:anthroforge:authoring:0.3.0'
    result.update({k: {} for k in ('sources', 'targets', 'frames', 'regions', 'recipes', 'muscles', 'volume_presets', 'policies', 'roster')})
    result['sources'] = {identity('/sources/'+k): v for k, v in document.get('sources', {}).items()}
    return result


def compile_document(document, inventory):
    output, domains = empty(document, inventory['reference_pose']), {}
    instances = deepcopy(document.get('instances', {}))
    for key, assembly in document.get('assemblies', {}).items():
        for name, instance in assembly['instances'].items():
            require(key+'__'+name not in instances, 'ASSEMBLY_COLLISION')
            instances[key+'__'+name] = instance
    for key, instance in instances.items():
        compile_instance(document, inventory, output, key, instance, domains)
    output['context']['units'] = physical_units(document, instances.values())
    validate_document(output)
    return dict(version='native_ir.v1', document=output, domains=domains, source_digest=digest(document))


def physical_units(document, instances):
    calibrations = [lookup(document, p).get('calibration') for p in {i['profile'] for i in instances}]
    defined = [c for c in calibrations if c]
    if not defined:
        return dict(mode='relative')
    require(len(defined) == len(calibrations), 'CALIBRATION_REQUIRED', 'Every participating profile must declare a compatible calibration.')
    for value in defined:
        require(value['evidence']['basis'] in ('measured', 'designer_authored'), 'CALIBRATION_EVIDENCE_REQUIRED')
    scales = {c['meters_per_scene_unit'] for c in defined}
    require(len(scales) == 1, 'CALIBRATION_CONFLICT')
    return dict(mode='metric', meters_per_scene_unit=next(iter(scales)))


def compile_instance(document, inventory, output, key, instance, domains):
    evaluation_profile(document, inventory, instance)
    recipe = lookup(document, instance['recipe'])
    require(instance['side'] != 'unknown', 'SIDE_REQUIRED', key)
    construction = strategy(recipe, instance)
    for role, reference in instance['bindings'].items():
        compile_region(document, inventory, output, reference, recipe['roles'][role]['purpose'])
        domains[identity(reference)] = reference
    output['volume_presets'][key] = compile_shape(document, instance)
    output['policies'][key] = native_values(lookup(document, instance['policy']), instance['profile'])
    output['recipes'][key] = dict(concept=lookup(document, recipe['concept'])['label'], architecture=recipe['strategy'].split('.')[0].replace('loop', 'ring'), region_roles=deepcopy(recipe['roles']), construction=construction, evidence=evidence(recipe['evidence']))
    output['muscles'][key] = dict(recipe=key, side=instance['side'], region_bindings=role_bindings(instance), volume_preset=key, policy=key, symmetry=dict(mode='explicit'))
    output['roster'][key] = dict(state='included', instances=[key], reason='Representative static volume; not anatomically reviewed.')


def evaluation_profile(document, inventory, instance):
    reference = instance.get('evaluation_profile', document.get('project', {}).get('evaluation_profile'))
    require(reference, 'STATIC_EVALUATION_PROFILE_REQUIRED')
    value = lookup(document, reference)
    require(value['purpose'] == 'static_avatar', 'STATIC_PROFILE_REQUIRED')
    require(value['reference_pose'] == inventory['reference_pose'], 'REFERENCE_POSE_MISMATCH')


def compile_shape(document, instance):
    shape = lookup(document, instance['shape'])
    volume = native_values(shape['native'], instance['profile'])
    shape_intent(volume, shape.get('intent', {}))
    return volume


def role_bindings(instance):
    result = {k: dict(region=identity(v), relationship='direct') for k, v in instance['bindings'].items()}
    for key, value in instance.get('supports', {}).items():
        result[key].update(relationship='support_proxy', reason=value['reason'], evidence=evidence(value['evidence']))
    return result


def shape_intent(volume, intent):
    for field, scale in [('amount', intent.get('height_scale', 1)), ('radius', intent.get('width_scale', 1))]:
        if field in volume:
            quantity = volume[field]
            key = 'value' if 'value' in quantity else 'fraction'
            quantity[key] *= scale
    if 'belly_position' in intent:
        require(volume['mode'] == 'control_point', 'BELLY_CONTROL_UNAVAILABLE')
        volume['control'][1] = intent['belly_position']
    if 'taper' in intent:
        volume['boundary']['along'] = intent['taper']


def strategy(recipe, instance):
    result = construction_strategies().get(recipe['strategy']).compile(recipe)
    values = {k: p['default'] for k, p in recipe['parameters'].items()}
    require(set(instance['parameters']) <= set(values), 'PARAMETER_UNDEFINED')
    values.update(instance['parameters'])
    for key, value in values.items():
        spec = recipe['parameters'][key]
        require(spec['minimum'] <= value <= spec['maximum'], 'PARAMETER_RANGE', key)
    apply_parameters(result, values)
    return result


def apply_parameters(construction, values):
    require(set(values) <= {'attachment_spread', 'nodes_per_fiber'}, 'UNSUPPORTED_PARAMETER')
    if 'nodes_per_fiber' in values:
        require(values['nodes_per_fiber'] == int(values['nodes_per_fiber']), 'INTEGER_PARAMETER_REQUIRED')
        construction['nodes_per_fiber'] = int(values['nodes_per_fiber'])
    if 'attachment_spread' not in values:
        return
    for station in construction.get('stations', []):
        sample = station['sample']
        require(sample['kind'] == 'curve_span', 'UNSUPPORTED_PARAMETER')
        center = (sample['start']+sample['end'])/2
        radius = (sample['end']-sample['start'])*values['attachment_spread']/2
        require(0 <= center-radius < center+radius <= 1, 'SAMPLING_OUTSIDE_DOMAIN')
        sample.update(start=center-radius, end=center+radius)


def compile_region(document, inventory, output, reference, purpose):
    region, key = lookup(document, reference), identity(reference)
    require(region.get('sampling'), 'SAMPLING_DOMAIN_REQUIRED', reference)
    frame_key = compile_frame(document, inventory, output, region)
    sampling = rewrite_frames(deepcopy(region['sampling']), frame_key)
    sampling['definition'] = resolve_sampling(sampling['definition'], region, document, inventory)
    output['regions'][key] = dict(frame=frame_key, concept=region['concept'], purpose=purpose, evidence=evidence(region['evidence']), **sampling)


def compile_frame(document, inventory, output, region):
    frame_ref = region['frame']
    spec = frame_spec(document, inventory, frame_ref)
    native = binding(document, inventory, spec['owner'])
    entity = lookup(document, lookup(document, spec['owner'])['entity'])
    target_key, frame_key = identity(spec['owner']), identity(frame_ref)
    output['targets'][target_key] = dict(concept=region['concept'], side=entity['side'], binding=dict(kind='scene_scp_id', id=native['instance_id']))
    output['frames'][frame_key] = dict(owner=target_key, kind='anatomical_box', axes_owner_local=spec['axes'], axis_labels=spec['axis_labels'], bounds='evaluated_geometry_at_reference_pose', editor_grid=64, evidence=evidence(spec['evidence']))
    return frame_key


def resolve_sampling(definition, region, document, inventory):
    if definition['kind'] != 'guide_curve':
        return definition
    guide = control(document, inventory, definition['control'])
    require(guide['kind'] == 'guide', 'GUIDE_CONTROL_REQUIRED')
    require(len(definition['t']) == len(definition['offsets']), 'GUIDE_SAMPLE_COUNT')
    chart = frame(document, inventory, region['frame'])
    seeds = [(coordinates(chart, guide_position(guide, t))+offset).tolist() for t, offset in zip(definition['t'], definition['offsets'])]
    return dict(kind='curve', closed=False, seeds=seeds)


def rewrite_frames(value, frame_key):
    if isinstance(value, dict):
        return {k: frame_key if k == 'frame' else rewrite_frames(v, frame_key) for k, v in value.items()}
    return [rewrite_frames(v, frame_key) for v in value] if isinstance(value, list) else value


def native_values(value, profile):
    if isinstance(value, list):
        return [native_values(v, profile) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: native_values(v, profile) for k, v in value.items()}
    if 'sources' in result:
        result['sources'] = [identity(r if r.startswith('/') else '/sources/'+r) for r in result['sources']]
    if 'frame' in result:
        result['frame'] = identity(profile+'/frames/'+result['frame'])
    return result
