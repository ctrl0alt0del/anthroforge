"""Live, revision-guarded base diagnostics; cached requests never replay old geometry."""
from time import perf_counter
from ...core.authoring.errors import AuthoringError
from ...core.authoring.reports import response, entity

OPS = ('muscles.base_intersections',)


def dispatch(service, request, started):
    params = request['params']
    if 'expected_scene_revision' in params: service.check(params)
    try: report = service.scene.base_intersections(params)
    except (ValueError, RuntimeError) as error:
        raise AuthoringError(str(error).split(':')[0], str(error)) from error
    result = response(request, service.inventory['revision'])
    result['entities'] = [entity(service.inventory['root_id'] or service.inventory['scene_id'],
        'muscle_base_intersections', state='resolved' if report['complete'] else 'unresolved', intersections=report)]
    if not report['complete']: result['status'] = 'unresolved'
    result['cost']['total_ms'] = (perf_counter()-started)*1000
    return result
