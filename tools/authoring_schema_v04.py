"""Generate pinned closed 0.4 schemas using only the audited vocabulary."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'core/authoring/schemas'
S = {'type': 'string', 'minLength': 1}
N = {'type': 'number'}
I = {'type': 'integer', 'minimum': 0}
B = {'type': 'boolean'}


def ref(name):
    return {'$ref': '#/$defs/' + name}


def enum(*values):
    return {'enum': list(values)}


def array(item, minimum=0, maximum=100000):
    return dict(type='array', items=item, minItems=minimum, maxItems=maximum)


def obj(properties, required=None):
    return dict(type='object', properties=properties, required=list(properties) if required is None else required, additionalProperties=False)


def mapping(item):
    return dict(type='object', propertyNames={'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_.-]*$'}, additionalProperties=item)


def tagged(kind, fields):
    return obj(dict(kind=enum(kind), **fields))


def choice(*items):
    return {'oneOf': list(items)}


def legacy(value):
    if isinstance(value, dict):
        return {k: v.replace('#/$defs/', '#/$defs/native_') if k == '$ref' else legacy(v) for k, v in value.items()}
    return list(map(legacy, value)) if isinstance(value, list) else value


def base_defs():
    old = json.loads((ROOT / 'authoring-0.3.schema.json').read_text())
    result = {'native_' + k: legacy(v) for k, v in old['$defs'].items()}
    result.update(xyz=array(N, 3, 3), axes=array(ref('xyz'), 3, 3), reference={'type': 'string', 'pattern': '^([A-Za-z][A-Za-z0-9_.-]*#)?/[^ ]+$'})
    result['evidence'] = obj(dict(basis=enum('measured', 'inferred', 'synthetic', 'designer_authored'), sources=array(ref('reference')), note=S))
    result['side'] = enum('left', 'right', 'midline', 'unknown')
    result['quantity'] = obj(dict(value=N, unit=enum('scene', 'mm', 'cm', 'm', 'ratio', 'scene2', 'scene3'), evidence=ref('evidence')))
    result['source'] = ref('native_source')
    for key in ('native_station', 'native_loop_anchor'):
        result[key]['required'].remove('offset')
    return result


def anatomy_defs(d):
    d['concept'] = obj(dict(label=S, ontology=S), ['label'])
    d['entity'] = obj(dict(concept=ref('reference'), side=ref('side'), label=S, evidence=ref('evidence')))
    d['relation'] = obj(dict(subject=ref('reference'), predicate=enum('part_of', 'attaches_to', 'adjacent_to', 'contralateral_to'), object=ref('reference'), evidence=ref('evidence')))
    d['claim'] = obj(dict(subject=ref('reference'), property=S, value=choice(S, N, ref('quantity')), evidence=ref('evidence')))
    d['review'] = obj(dict(subject=ref('reference'), state=enum('unreviewed', 'accepted', 'rejected'), input_digest=S, note=S))
    d['binding'] = obj(dict(entity=ref('reference'), scp_id=S, instance_id=S), ['entity', 'scp_id'])
    d['frame'] = frame_schema()
    d['landmark'] = obj(dict(frame=ref('reference'), q=ref('xyz'), evidence=ref('evidence')))
    d['control'] = obj(dict(instance_id=S, kind=enum('guide', 'hook', 'profile', 'lattice'), reference_digest=S, evidence=ref('evidence')))
    d['control']['properties']['reference_points'] = array(ref('xyz'), 2, 4096)


def frame_schema():
    common = dict(owner=ref('reference'), axis_labels=array(S, 3, 3), evidence=ref('evidence'))
    box = obj(dict(kind=enum('box'), axes=ref('axes'), **common))
    landmark = obj(dict(kind=enum('landmark_box'), origin=ref('reference'), axis_point=ref('reference'), plane_point=ref('reference'), **common))
    return choice(box, landmark)


def query_defs(d):
    d['surface_patch'] = choice(obj(dict(triangle=I, polygon=array(ref('xyz'), 3, 128))), obj(dict(tri_vidx=array(I, 3, 3), face_vidx=array(I, 3, 4096), polygon=array(ref('xyz'), 3, 128), occurrence=I), ['tri_vidx', 'polygon']))
    d['selector'] = choice(tagged('box', dict(low=ref('xyz'), high=ref('xyz'))), tagged('ellipsoid', dict(center=ref('xyz'), radii=ref('xyz'), depth={'type': 'integer', 'minimum': 1, 'maximum': 8})))
    booleans = [tagged(k, dict(operands=array(ref('query'), 2, 16))) for k in ('union', 'intersection', 'difference')]
    d['query'] = choice(tagged('region', dict(ref=ref('reference'))), tagged('selector', dict(selector=ref('selector'))), *booleans,
                        tagged('half_space', dict(landmark=ref('reference'), normal=ref('xyz'))),
                        tagged('guide_interval', dict(control=ref('reference'), interval=array(N, 2, 2), radius=N, depth={'type': 'integer', 'minimum': 1, 'maximum': 8})),
                        tagged('connected', dict(query=ref('query'), seed=ref('xyz'), tolerance=N)), tagged('surface_patch', dict(topology_digest=S, patches=array(ref('surface_patch'), 1, 25000))))
    guide_curve = tagged('guide_curve', dict(control=ref('reference'), t=array({'type': 'number', 'minimum': 0, 'maximum': 1}, 2, 128), offsets=array(ref('xyz'), 2, 128)))
    d['sampling'] = obj(dict(definition=choice(ref('native_region_shape'), guide_curve), projection=ref('native_projection')))
    d['region'] = obj(dict(owner=ref('reference'), frame=ref('reference'), reference_pose=S, concept=S, query=ref('query'), sampling=ref('sampling'), evidence=ref('evidence')), ['owner', 'frame', 'reference_pose', 'concept', 'query', 'evidence'])
    d['measurement'] = choice(tagged('distance', dict(first=ref('reference'), second=ref('reference'), unit=enum('scene'), evidence=ref('evidence'))), tagged('value', dict(quantity=ref('quantity'))))
    d['calibration'] = obj(dict(meters_per_scene_unit={'type': 'number', 'exclusiveMinimum': 0}, evidence=ref('evidence')))
    fields = dict(reference_pose=S, bindings=mapping(ref('binding')), frames=mapping(ref('frame')), controls=mapping(ref('control')), landmarks=mapping(ref('landmark')), regions=mapping(ref('region')), measurements=mapping(ref('measurement')), calibration=ref('calibration'))
    d['profile'] = obj(fields, [k for k in fields if k != 'calibration'])


def requirement_defs(d):
    d['constraint'] = choice(tagged('side', dict(value=ref('side'))), tagged('control_kind', dict(value=enum('guide', 'hook', 'profile', 'lattice'))), tagged('dimension', dict(value=enum('length', 'area', 'volume', 'ratio'))), tagged('capability', dict(value=S)))
    fields = dict(target=ref('reference'), need=enum('entity', 'binding', 'frame', 'landmark', 'region', 'measurement', 'control', 'capability'), depends_on=array(ref('reference')), consumers=array(ref('reference')), constraints=array(ref('constraint')), required_state=enum('resolved', 'provisional'), evidence=ref('evidence'))
    d['requirement'] = obj(fields)
    d['proposal'] = choice(tagged('binding', dict(value=ref('binding'))), tagged('frame', dict(value=ref('frame'))), tagged('landmark', dict(value=ref('landmark'))), tagged('region', dict(value=ref('region'))), tagged('control', dict(value=ref('control'))), tagged('measurement', dict(value=ref('measurement'))))
    d['candidate_parameters'] = obj(dict(instance_id=S, proposal=ref('proposal')), [])


def shape_defs(d):
    d['parameter'] = obj(dict(default=N, minimum=N, maximum=N, unit=enum('ratio', 'scene'), evidence=ref('evidence')))
    fields = dict(strategy=enum('fusiform.v1', 'fan.v1', 'strap.v1', 'loop.v1'), concept=ref('reference'), roles=mapping(ref('native_role')), construction=choice(ref('native_open_loft'), ref('native_closed_loft')), parameters=mapping(ref('parameter')), shape=ref('reference'), evidence=ref('evidence'))
    d['recipe'] = obj(fields)
    d['shape'] = obj(dict(native=ref('native_volume'), targets=array(ref('shape_target')), fitting=ref('fitting'), evidence=ref('evidence')))
    d['shape']['properties']['intent'] = obj(dict(width_scale={'type': 'number', 'exclusiveMinimum': 0}, height_scale={'type': 'number', 'minimum': 0}, belly_position={'type': 'number', 'minimum': 0, 'maximum': 1}, taper={'type': 'number', 'minimum': 0, 'maximum': .5}), [])
    d['shape_target'] = obj(dict(metric=enum('width', 'height', 'belly_position', 'volume', 'area'), range=array(N, 2, 2), closure=enum('none', 'planar_caps'), hard=B))
    d['fitting'] = obj(dict(enabled=B, parameters=array(enum('max_inflation', 'radius', 'direction_depth', 'boundary_strength', 'boundary_band', 'boundary_power')), max_evaluations={'type': 'integer', 'minimum': 1, 'maximum': 128}, step={'type': 'number', 'exclusiveMinimum': 0}))
    d['instance'] = obj(dict(recipe=ref('reference'), profile=ref('reference'), bindings=mapping(ref('reference')), shape=ref('reference'), parameters=mapping(N), policy=ref('reference'), side=ref('side'), evidence=ref('evidence')))
    d['instance']['properties']['supports'] = mapping(obj(dict(reason=S, evidence=ref('evidence'))))
    route_defs(d)
    d['assembly'] = obj(dict(instances=mapping(ref('instance')), evidence=ref('evidence')))
    d['evaluation_profile'] = obj(dict(purpose=enum('static_avatar'), reference_pose=S, checks=array(enum('attachments', 'shape', 'inflated_contacts', 'requirements')), required_capabilities=array(S)))
    d['scenario'] = obj(dict(profile=ref('reference'), evaluation_profile=ref('reference'), parameter_overrides=mapping(N), evidence=ref('evidence')))
    d['override'] = obj(dict(subject=ref('reference'), native_id=S, baseline_digest=S, value=ref('proposal'), evidence=ref('evidence')))


def route_defs(d):
    d['instance']['properties']['evaluation_profile'] = ref('reference')
    weights = array(dict(type='number', minimum=-1e-8, maximum=1.00000001), 3, 3)
    d['surface_binding'] = obj(dict(tri_vidx=array(I, 3, 3), tri_weights=weights))
    guessed = obj(dict(region=ref('reference'), seed=ref('xyz'), offset=N), ['region', 'seed'])
    bound = obj(dict(region=ref('reference'), seed=ref('xyz'), offset=N, surface_binding=ref('surface_binding')), ['region', 'surface_binding'])
    d['route_anchor'] = choice(guessed, bound)
    d['instance']['properties']['route_overrides'] = mapping(obj(dict(anchors=array(ref('route_anchor'), 2, 128), evidence=ref('evidence'))))
    explicit = obj(dict(mode=enum('explicit')))
    mirror = obj(dict(mode=enum('native_mirror'), plane_frame=ref('reference'), plane_axis=enum('x', 'y', 'z'), plane_coordinate=dict(type='number', minimum=0, maximum=1)))
    d['instance_symmetry'] = choice(explicit, mirror)
    d['instance']['properties']['symmetry'] = ref('instance_symmetry')


def authoring():
    d = base_defs()
    for add in (anatomy_defs, query_defs, requirement_defs, shape_defs):
        add(d)
    collections = {'concepts': 'concept', 'entities': 'entity', 'relations': 'relation', 'sources': 'source', 'claims': 'claim', 'reviews': 'review', 'skeleton_profiles': 'profile', 'requirements': 'requirement', 'recipes': 'recipe', 'assemblies': 'assembly', 'shape_presets': 'shape', 'evaluation_profiles': 'evaluation_profile', 'scenarios': 'scenario', 'instances': 'instance', 'policies': 'native_policy', 'overrides': 'override'}
    fields = {k: mapping(ref(v)) for k, v in collections.items()}
    fields.update(dsl=enum('anthroforge.authoring'), version=enum('0.4.0'), document_id=ref('native_id'), revision=I, kind=enum('project', 'library', 'skeleton_profile'), requires=array(S))
    fields['imports'] = mapping(obj(dict(path=S, document_id=S, version=S, sha256={'type': 'string', 'pattern': '^[a-fA-F0-9]{64}$'})))
    fields['project'] = obj(dict(skeleton_profile=ref('reference'), evaluation_profile=ref('reference')))
    fields['limits'] = obj(dict(max_fibers={'type': 'integer', 'minimum': 1, 'maximum': 4096}, max_surface_vertices={'type': 'integer', 'minimum': 1, 'maximum': 1000000}, max_milliseconds={'type': 'integer', 'minimum': 1, 'maximum': 3600000}), [])
    fields['$schema'] = S
    result = obj(fields, ['dsl', 'version', 'document_id', 'revision', 'kind'])
    result.update({'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'urn:anthroforge:authoring:0.4.0', '$defs': d})
    return result


def operation(op, fields, required):
    params = dict(scene_id=S, **fields)
    fields = dict(message_type=enum('request'), version=enum('0.4.0'), request_id=S, op=enum(op), params=obj(params, ['scene_id'] + required))
    return obj(dict(dsl=enum('anthroforge.authoring.protocol'), **fields), list(fields))


def protocol(definitions):
    ident = dict(document_id=S)
    mutation = dict(**ident, expected_draft_revision=I, expected_scene_revision=S)
    patch = array(obj(dict(op=enum('add', 'replace', 'remove'), path=S, value=ref('patch_value')), ['op', 'path']))
    operations = basic_operations(ident, mutation, patch) + candidate_operations(mutation) + visual_operations() + [snap_points_operation(), catalog_operation()]
    definitions['patch_value'] = choice({'type': 'string'}, N, B, array(ref('patch_value')), dict(type='object', additionalProperties=ref('patch_value')))
    definitions['document'] = {k: v for k, v in authoring().items() if k != '$defs'}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'urn:anthroforge:protocol:0.4.0', '$defs': definitions, 'oneOf': operations+[response()]}


def response():
    fields = dict(dsl=enum('anthroforge.authoring.protocol'), version=enum('0.4.0'), message_type=enum('response'), request_id=S, op=S, status=enum('success', 'unresolved', 'failed'), scene_id=S, scene_revision=S, published=B, entities=array(ref('patch_value')), diagnostics=array(ref('patch_value')), assets=array(ref('patch_value')), cost=ref('patch_value'))
    required = list(fields)
    names = 'draft_revision normalized_patch affected receipt evaluation unsupported replayed recovery root_id initialized inventory capabilities operations document state dependencies provenance purpose anatomical_review first second comparison_assets search_state missing candidates ranking candidate native_ids generation recovered_copy generation_id draft restored_active_scene comparison authored_changed scenarios normalized_overrides views view hits selection coverage'
    fields.update({k: ref('patch_value') for k in names.split()})
    fields['matches'] = array(ref('patch_value'))
    fields['catalog'] = ref('patch_value')
    return obj(fields, required)


def basic_operations(ident, mutation, patch):
    operations = [operation('anatomy.' + op, ident, [] if op == 'discover' else ['document_id']) for op in ('discover', 'requirements', 'export', 'inspect', 'explain', 'validate')]
    operations += [operation('anatomy.initialize', dict(expected_scene_revision=S), ['expected_scene_revision'])]
    operations += [operation('anatomy.draft', dict(**mutation, document=ref('document')), list(mutation) + ['document'])]
    operations += [operation('anatomy.patch', dict(**mutation, patch=patch), list(mutation) + ['patch'])]
    operations += [operation('anatomy.' + op, mutation, list(mutation)) for op in ('compile', 'resume', 'publish', 'checkpoint', 'upgrade_regions')]
    operations += [operation('anatomy.reconcile', dict(**mutation, mode=enum('inspect', 'restore', 'adopt')), list(mutation) + ['mode'])]
    operations += [operation('anatomy.compare', dict(**ident, other_document_id=S), ['document_id', 'other_document_id'])]
    operations += [operation('anatomy.recover', dict(generation_id=S, output_path=S), ['generation_id', 'output_path'])]
    query = choice(tagged('entities', dict(concept=ref('reference'), side=ref('side'))), tagged('region', dict(reference=ref('reference'))), tagged('relations', dict(subject=ref('reference'))))
    operations += [operation('anatomy.query', dict(**ident, query=query), ['document_id', 'query'])]
    operations += [operation('anatomy.cancel', dict(**ident, compilation_request_id=S), ['document_id', 'compilation_request_id'])]
    return operations


def candidate_operations(mutation):
    fields = dict(**mutation, requirement=S, provider=enum('existing_control.v1', 'authored_definition.v1', 'construction_rule.v1'), parameters=ref('candidate_parameters'))
    result = [operation('anatomy.propose_binding', fields, list(fields))]
    result += [operation('anatomy.inspect_candidate', dict(document_id=S, candidate_id=S), ['document_id', 'candidate_id'])]
    fields = dict(**mutation, candidate_id=S, proposal=ref('proposal'))
    result += [operation('anatomy.revise_candidate', fields, list(fields))]
    fields = dict(**mutation, candidate_id=S, mode=enum('resolved', 'provisional'))
    return result + [operation('anatomy.adopt_binding', fields, list(fields))]


def snap_points_operation():
    fields = dict(instance_id=S, expected_scene_revision=S, points=array(ref('xyz'), 1, 256))
    fields.update(max_distance={'type': 'number', 'minimum': 0}, collision_radius={'type': 'number', 'minimum': 0})
    return operation('anatomy.snap_points', fields, ['instance_id', 'expected_scene_revision', 'points'])


def catalog_operation():
    fields = dict(document_id=S, profile=ref('reference'), scp_id=S, instance_id=S, side=ref('side'), text=S, sampling_available=B)
    fields.update(offset=I, limit=dict(type='integer', minimum=1, maximum=200))
    return operation('anatomy.catalog', fields, [])


def visual_operations():
    fields = dict(instance_id=S, expected_scene_revision=S, resolution={'type': 'integer', 'minimum': 64, 'maximum': 1024}, context_ids=array(S, 0, 64))
    rows = [operation('anatomy.views', fields, ['instance_id', 'expected_scene_revision'])]
    fields = dict(view_id=S, azimuth=N, elevation={'type': 'number', 'minimum': -90, 'maximum': 90}, zoom={'type': 'number', 'minimum': .1, 'maximum': 20}, center=ref('xyz'), point_id=S, label=S, display=obj(dict(edges=B, controls=B), []))
    fields.update(section=obj(dict(normal=ref('xyz'), distance=N)), clear_section=B, context_ids=array(S, 0, 64))
    rows += [operation('anatomy.view', fields, ['view_id'])]
    uv = array({'type': 'number', 'minimum': 0, 'maximum': 1}, 2, 2)
    rows += [operation('anatomy.pick', dict(view_id=S, points=array(uv, 1, 64)), ['view_id', 'points'])]
    return rows+[operation('anatomy.highlight', dict(view_ids=array(S, 1, 16), point_ids=array(S, 1, 64)), ['view_ids', 'point_ids'])]+visual_region_operations(uv)


def visual_region_operations(uv):
    fields = dict(view_id=S, polygon=array(uv, 3, 64), selection_id=S, mode=enum('add', 'subtract'))
    rows = [operation('anatomy.select_region', fields, ['view_id', 'polygon'])]
    fields = dict(selection_id=S, view_ids=array(S, 1, 16))
    rows += [operation('anatomy.inspect_selection', fields, list(fields))]
    fields = dict(document_id=S, expected_scene_revision=S, expected_draft_revision=I, selection_id=S, requirement=S, frame=ref('reference'), concept=S, note=S)
    return rows+[operation('anatomy.propose_region', fields, list(fields)), operation('anatomy.coverage', dict(view_ids=array(S, 1, 32)), ['view_ids'])]


def main():
    document = authoring()
    for name, value in [('authoring', document), ('protocol', protocol(dict(document['$defs'])))]:
        (ROOT / (name + '-0.4.schema.json')).write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    main()
