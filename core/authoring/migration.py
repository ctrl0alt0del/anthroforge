"""Import earlier document formats into canonical anatomical profiles."""
from copy import deepcopy


def migrate(document, instances=None):
    profile = dict(reference_pose=document['context']['reference_pose'], **{k: {} for k in ('bindings', 'frames', 'controls', 'landmarks', 'regions', 'measurements')})
    result = dict(dsl='anthroforge.authoring', version='0.4.0', document_id=document['document_id'], revision=0, kind='project', sources=deepcopy(document['sources']), concepts={}, entities={}, skeleton_profiles=dict(default=profile), recipes={}, shape_presets={}, instances={}, policies=deepcopy(document['policies']))
    targets(document, result, profile, instances or {})
    regions(document, profile)
    recipes(document, result)
    result['evaluation_profiles'] = dict(static=dict(purpose='static_avatar', reference_pose=profile['reference_pose'], checks=['attachments', 'shape', 'inflated_contacts', 'requirements'], required_capabilities=['static_avatar.v1']))
    result['project'] = dict(skeleton_profile='/skeleton_profiles/default', evaluation_profile='/evaluation_profiles/static')
    return result


def proof(old):
    return dict(old, sources=['/sources/'+r for r in old['sources']])


def path(group, key):
    return '/skeleton_profiles/default/'+group+'/'+key


def targets(old, new, profile, instances):
    default = proof(next(iter(old['frames'].values()))['evidence'])
    for key, value in old['targets'].items():
        new['concepts'][key] = dict(label=value['concept'])
        new['entities'][key] = dict(concept='/concepts/'+key, side=value['side'], label=value['concept'], evidence=default)
        native = value['binding']['id']
        profile['bindings'][key] = dict(entity='/entities/'+key, scp_id=native)
        if native in instances:
            profile['bindings'][key]['instance_id'] = instances[native]
    for key, value in old['frames'].items():
        profile['frames'][key] = dict(owner=path('bindings', value['owner']), kind='box', axes=value['axes_owner_local'], axis_labels=value['axis_labels'], evidence=proof(value['evidence']))


def regions(old, profile):
    for key, value in old['regions'].items():
        owner = profile['frames'][value['frame']]['owner']
        query = dict(kind='selector', selector=dict(kind='box', low=[-.001]*3, high=[1.001]*3))
        sampling = dict(definition=deepcopy(value['definition']), projection=deepcopy(value['projection']))
        profile['regions'][key] = dict(owner=owner, frame=path('frames', value['frame']), reference_pose=profile['reference_pose'], concept=value['concept'], query=query, sampling=sampling, evidence=proof(value['evidence']))


def recipes(old, new):
    for key, value in old['recipes'].items():
        concept = 'muscle_'+key
        new['concepts'][concept] = dict(label=value['concept'])
        family = dict(sheet='fan', ring='loop').get(value['architecture'], value['architecture'])
        new['recipes'][key] = dict(strategy=family+'.v1', concept='/concepts/'+concept, roles=deepcopy(value['region_roles']), construction=deepcopy(value['construction']), parameters={}, shape='/shape_presets/'+next(iter(old['volume_presets'])), evidence=proof(value['evidence']))
    for key, value in old['volume_presets'].items():
        new['shape_presets'][key] = dict(native=deepcopy(value), targets=[], fitting=dict(enabled=False, parameters=['max_inflation', 'radius', 'direction_depth'], max_evaluations=12, step=.1), evidence=proof(value['evidence']))
    for key, value in old['muscles'].items():
        new['instances'][key] = dict(recipe='/recipes/'+value['recipe'], profile='/skeleton_profiles/default', bindings={k: path('regions', v['region']) for k, v in value['region_bindings'].items()}, shape='/shape_presets/'+value['volume_preset'], parameters={}, policy='/policies/'+value['policy'], side=value['side'], evidence=proof(old['recipes'][value['recipe']]['evidence']))
        new['instances'][key]['supports'] = {k: dict(reason=v['reason'], evidence=proof(v['evidence'])) for k, v in value['region_bindings'].items() if v['relationship'] == 'support_proxy'}
