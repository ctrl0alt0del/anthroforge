"""Keep optional mesh inspection outside the SCP discovery inventory."""
from ...core.authoring.errors import require


def prepare(service, params):
    method = getattr(service.scene, 'visual_inventory', None)
    if callable(method):
        service.inventory, owner = method(service.inventory, params)
    else:
        require('source_object' not in params and not params.get('context_objects'), 'UNSUPPORTED_CAPABILITY')
        owner = params['instance_id']
    result = dict(params, instance_id=owner)
    if 'context_objects' in params:
        result['context_ids'] = params.get('context_ids', [])+['OBJECT:'+n for n in params['context_objects']]
    return result


def refresh(service, scene):
    names = list(scene.get('object_sources', {}).values())
    if names:
        method = getattr(service.scene, 'visual_refresh', None)
        require(callable(method), 'UNSUPPORTED_CAPABILITY')
        service.inventory = method(service.inventory, names)
