"""Session-scoped native recompute jobs; polling never captures or solves geometry."""
from ...core.authoring.codec import digest
from ...core.authoring.errors import require
from ...core.visualization import fiber_refinement as runtime
from ...core.warnings import session

_REQUESTS, _TOKENS = {}, {}
_EPOCH = ''


def scope(root, scene):
    global _EPOCH
    if _EPOCH != session.EPOCH:
        _REQUESTS.clear(); _TOKENS.clear(); _EPOCH = session.EPOCH
    return (session.EPOCH, int(scene.session_uid), int(root.session_uid))


def replay(root, scene, request):
    row = _REQUESTS.get((*scope(root, scene), request['request_id']))
    if row is None: return None
    require(row['digest'] == digest(request), 'REQUEST_ID_REUSED')
    return dict(status(root, scene, row['token']), replayed=True)


def selected(root, scene, params):
    available = {str(f.id) for f in root.af_vcp_system.fibers}
    ids = list(params.get('fiber_ids', sorted(available)))
    require(bool(ids), 'NO_FIBERS')
    require(len(ids) == len(set(ids)), 'DUPLICATE_FIBER_ID')
    require(set(ids) <= available, 'FIBER_NOT_FOUND', ', '.join(sorted(set(ids)-available)))
    require(not any(runtime.fiber_refinement_state(scene, key) == 'REFINING' for key in ids), 'FIBER_RECOMPUTE_BUSY')
    return ids


def start(root, scene, request):
    ids = selected(root, scene, request['params'])
    if request['params'].get('cold_start', True): clear_cache(root, scene, ids)
    token = runtime.request_fiber_refinement_group(root, scene, ids, quality='FINAL')
    identity = scope(root, scene)
    _REQUESTS[(*identity, request['request_id'])] = dict(digest=digest(request), token=token)
    _TOKENS[token] = identity
    return status(root, scene, token)


def clear_cache(root, scene, ids):
    from ...core.vcp.fiber_v2_runtime import clear_v3_runtime_warm_cache
    from ...core.visualization.fiber_sync import register_fiber_sync
    clear_v3_runtime_warm_cache(scene, root, set(ids))
    sync = register_fiber_sync()
    for key in ids: sync.clear_solver_cache(key)


def status(root, scene, token):
    require(_TOKENS.get(token) == scope(root, scene), 'RECOMPUTE_JOB_NOT_FOUND')
    value = runtime.fiber_refinement_group_state(token)
    require(value is not None, 'RECOMPUTE_JOB_NOT_FOUND')
    from ...core.vcp.runtime_state import fiber_recompute_status
    fibers = {str(f.id): f for f in root.af_vcp_system.fibers}
    states = {key: fiber_recompute_status(fibers[key]) if key in fibers else 'DELETED' for key in value['targets']}
    value = {key: list(row) if isinstance(row, tuple) else row for key, row in value.items()}
    value.update(statuses=states, total=len(value['targets']), completed=len(value['targets'])-len(value['pending']))
    return dict(recompute=value, published=bool(value['committed']),
                status='unresolved' if value['done'] and value['failures'] else 'success')
