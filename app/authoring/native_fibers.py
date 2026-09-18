"""Authoring access to ordinary native fiber recompute and live progress."""
from ...core.authoring.errors import require
from ...core.authoring.reports import response

OPERATIONS = ('fibers.recompute', 'fibers.recompute_status')


def execute(port, request):
    from ...adapters.authoring import fiber_recompute as jobs
    params, root, scene = request['params'], port.root, port.scene
    require(params['scene_id'] == root.name, 'SCENE_NOT_FOUND')
    result = response(request)
    if request['op'] == 'fibers.recompute_status':
        return dict(result, **jobs.status(root, scene, params['token']))
    cached = jobs.replay(root, scene, request)
    if cached is not None: return dict(result, **cached)
    from ...adapters.authoring.inventory import capture
    revision = capture(root, scene)['revision']
    require(params['expected_scene_revision'] == revision, 'STALE_SCENE_REVISION')
    result.update(jobs.start(root, scene, request), scene_revision=revision)
    return result
