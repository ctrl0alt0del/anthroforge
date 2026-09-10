"""Anatomical operation dispatch, with injected scene and storage ports."""
from time import perf_counter
from ...core.authoring.reports import response
from ...core.authoring.errors import require
from ...core.authoring.repository import DraftRepository
from ...core.authoring.model import Registry, InventoryPort, IdentityPort, PublicationPort, NativeEditPort, CheckpointPort
from ...core.authoring.candidates import AuthoredDefinition, ExistingControl, ConstructionRule
from . import drafts, queries, bindings


class AuthoringService:
    def __init__(self, scene: InventoryPort, solver, store, identities: IdentityPort = None, publication: PublicationPort = None, native_edits: NativeEditPort = None, checkpoints: CheckpointPort = None):
        self.scene, self.solver, self.store = scene, solver, store
        self.identities, self.publication = identities or scene, publication or scene
        self.native_edits, self.checkpoints = native_edits or scene, checkpoints or scene
        self.providers = Registry()
        for key, provider in [('existing_control.v1', ExistingControl()), ('authored_definition.v1', AuthoredDefinition()), ('construction_rule.v1', ConstructionRule())]:
            self.providers.add(key, provider)
        self.inventory, self.repository = None, None

    def execute(self, request):
        started = perf_counter()
        self.request_id = request['request_id']
        self.inventory = self.scene.capture_authoring()
        require(request['params']['scene_id'] == self.inventory['scene_id'], 'SCENE_NOT_FOUND')
        self.repository = DraftRepository(self.store, self.inventory['root_id'] or self.inventory['scene_id'])
        return self.dispatch(request, started)

    def dispatch(self, request, started):
        if request['op'] == 'anatomy.snap_points':
            self.check(request['params'])
        cached = replay_response(self, request)
        if cached:
            return cached
        handler = operations().get(request['op'])
        require(handler is not None, 'UNSUPPORTED_CAPABILITY', request['op'])
        result = response(request, self.inventory['revision'])
        result.update(handler(self, request))
        remember_journal(self, request)
        return finish_response(self, request, result, started)

    def load(self, params):
        record = self.repository.get(params['document_id'])
        require(record is not None, 'DRAFT_NOT_FOUND')
        return record

    def check(self, params, record=None):
        require(params['expected_scene_revision'] == self.inventory['revision'], 'STALE_SCENE_REVISION')
        if record is not None:
            require(record['draft_revision'] == params['expected_draft_revision'], 'STALE_DRAFT_REVISION')


def operations():
    result = {'anatomy.'+name: getattr(queries, name) for name in ('discover', 'query', 'requirements', 'export', 'inspect', 'explain', 'validate', 'compare')}
    result.update({'anatomy.'+name: getattr(drafts, name) for name in ('initialize', 'draft', 'patch')})
    result.update({'anatomy.'+name: getattr(bindings, name) for name in ('propose_binding', 'inspect_candidate', 'revise_candidate', 'adopt_binding')})
    from . import construction, persistence, reconciliation, visual
    result.update({'anatomy.'+name: getattr(construction, name) for name in ('compile', 'publish')})
    result.update({'anatomy.'+name: getattr(persistence, name) for name in ('checkpoint', 'recover')})
    result['anatomy.reconcile'] = reconciliation.reconcile
    from .resources import cancel
    from .surface_points import snap_points
    result.update({'anatomy.cancel': cancel, 'anatomy.resume': construction.compile, 'anatomy.snap_points': snap_points})
    result.update(visual.operations())
    return result


def capabilities():
    return ['static_avatar.v1', 'box.v1', 'landmark_box.v1', 'ellipsoid.sampled.v1', 'guide_band.sampled.v1', 'region_boolean.v1', 'requirements.v1', 'existing_control.v1', 'authored_definition.v1', 'construction_rule.v1', 'fusiform.v1', 'fan.v1', 'strap.v1', 'loop.v1', 'route_override.v1', 'cancellation.v1', 'visual_inspection.v1', 'visual_selection.v1', 'surface_patch.v1', 'surface_point_picker.v1']


def remember_journal(service, request):
    mutations = {'initialize', 'draft', 'patch', 'adopt_binding', 'publish', 'reconcile', 'checkpoint'}
    if request['op'].split('.')[-1] in mutations:
        service.identities.remember_journal(service.store.directory)


def finish_response(service, request, result, started):
    from ...core.authoring.codec import digest
    result['cost']['total_ms'] = (perf_counter()-started)*1000
    key = [service.inventory['root_id'] or service.inventory['scene_id'], request['request_id']]
    service.store.put('v04_requests', key, dict(digest=digest(request), response=result))
    return result


def replay_response(service, request):
    from ...core.authoring.codec import digest
    key = [service.inventory['root_id'] or service.inventory['scene_id'], request['request_id']]
    cached = service.store.get('v04_requests', key)
    if cached:
        require(cached['digest'] == digest(request), 'REQUEST_ID_REUSED')
        return dict(cached['response'], replayed=True)
    record = service.repository.get(request['params'].get('document_id', '')) or {}
    receipt = service.repository.replay(record, request)
    if receipt and 'response' in receipt:
        result = response(request, service.inventory['revision'])
        result.update(receipt['response'], replayed=True)
        return result
    return None
