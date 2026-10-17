"""Read-only, revision-guarded native tightening; commit with fibers.path_update."""
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.reports import response
from ...adapters.authoring.inventory import capture
from ...adapters.authoring.fiber_tightening import preview


def execute(port, request):
    root, scene, params = port.root, port.scene, request['params']
    require(params['scene_id'] == root.name, 'SCENE_NOT_FOUND')
    revision = capture(root, scene)['revision']
    require(params['expected_scene_revision'] == revision, 'STALE_SCENE_REVISION')
    fiber = next((f for f in root.af_vcp_system.fibers if f.id == params['fiber_id']), None)
    require(fiber is not None, 'FIBER_NOT_FOUND')
    require(params['expected_path_revision'] == fiber.free_path_revision, 'STALE_PATH_REVISION')
    try: result = preview(root, scene, fiber, params)
    except AuthoringError: raise
    except (ValueError, RuntimeError) as error: raise AuthoringError('TIGHTENING_UNRESOLVED', str(error)) from error
    require(capture(root, scene)['revision'] == revision, 'STALE_SCENE_REVISION')
    return dict(response(request, revision), entities=[result])
