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
        from ...core.authoring.request_identity import reservation
        self.repository = DraftRepository(self.store, self.inventory['root_id'] or self.inventory['scene_id'])
        with reservation(self.store, request, (self.inventory['root_id'] or self.inventory['scene_id'], self.inventory['scene_id'])):
            return self.dispatch(request, started)

    def dispatch(self, request, started):
        from . import native_profiles
        if request["op"] in native_profiles.OPS:
            return native_profiles.dispatch(self, request, started)
        check_live_preview(self, request)
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
    result.update({'anatomy.'+name: getattr(drafts, name) for name in ('initialize', 'draft', 'patch', 'upgrade_regions')})
    result.update({'anatomy.'+name: getattr(bindings, name) for name in ('propose_binding', 'inspect_candidate', 'revise_candidate', 'adopt_binding')})
    from . import construction, persistence, reconciliation, visual
    result.update({'anatomy.'+name: getattr(construction, name) for name in ('compile', 'publish')})
    result.update({'anatomy.'+name: getattr(persistence, name) for name in ('checkpoint', 'recover')})
    result['anatomy.reconcile'] = reconciliation.reconcile
    from .resources import cancel
    from .catalog import catalog
    result.update({'anatomy.cancel': cancel, 'anatomy.resume': construction.compile, 'anatomy.catalog': catalog})
    from .transfers import operations as transfer_operations
    from .native_profiles import operations as profile_operations
    return dict(result, **point_operations(), **visual.operations(), **transfer_operations(), **profile_operations())


def capabilities():
    return ['muscle_inflation_envelope.v1', 'transfer_constraints.v1', 'transfer_attachment_bands.v1', 'base_partition.v1', 'continuous_attachment.v1', 'shape_preserving_transfer.v1', 'smooth_native_base.v1', 'transfer_collisions.v1', 'transfer_correction.v1', 'free_fibers.v1', 'muscle_output_domain.v1', 'section_profile.v1', 'muscle_from_surface.v1', 'static_avatar.v1', 'box.v1', 'landmark_box.v1', 'ellipsoid.sampled.v1', 'guide_band.sampled.v1', 'region_boolean.v1', 'requirements.v1', 'existing_control.v1', 'authored_definition.v1', 'construction_rule.v1', 'fusiform.v1', 'fan.v1', 'strap.v1', 'loop.v1', 'branched_loft.v1', 'shared_points.v1', 'route_override.v1', 'cancellation.v1', 'visual_inspection.v1', 'visual_selection.v1', 'surface_patch.v1', 'surface_point_picker.v1', 'fiber_layout_planner.v1', 'skeleton_transfer.v1', 'muscle_base.v1', 'native_base.v1', 'skeleton_transfer.experimental.v1', 'muscle_base.experimental.v1']


def point_operations():
    from .base_partitions import operations as partition_operations
    from .smooth_bases import operations as smooth_operations
    from .surface_points import snap_points
    from .fiber_plans import plan_fibers
    from .base_surfaces import prepare_base
    from .base_definitions import define_base
    from .base_planning import plan_base_fibers
    from .base_publication import publish_base_fibers
    from .base_preparation import base_candidates, repair_volume
    return {**partition_operations(), **smooth_operations(), 'anatomy.snap_points': snap_points, 'anatomy.plan_fibers': plan_fibers, 'anatomy.prepare_base': prepare_base,
            'anatomy.base_candidates': base_candidates, 'anatomy.repair_volume': repair_volume,
            'anatomy.define_base': define_base, 'anatomy.plan_base_fibers': plan_base_fibers, 'anatomy.publish_base_fibers': publish_base_fibers}


def check_live_preview(service, request):
    if request['op'] in ('anatomy.snap_points', 'anatomy.partition_base_surfaces'):
        service.check(request['params'])
    elif request['op'] == 'anatomy.plan_fibers':
        service.check(request['params'], service.load(request['params']))


def remember_journal(service, request):
    mutations = {'initialize', 'draft', 'patch', 'upgrade_regions', 'adopt_binding', 'publish', 'reconcile', 'checkpoint', 'repair_volume'}
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
    if request['op'].startswith(('anatomy.transfer_', 'anatomy.smooth_base_')) or request['op'] in ('anatomy.prepare_base', 'anatomy.define_base', 'anatomy.plan_base_fibers', 'anatomy.publish_base_fibers', 'anatomy.base_candidates', 'anatomy.repair_volume'):
        return check_transfer_request(service, request)
    key = [service.inventory['root_id'] or service.inventory['scene_id'], request['request_id']]
    cached = current_preview_cache(service.store.get('v04_requests', key), request)
    if cached:
        require(cached['digest'] == digest(request), 'REQUEST_ID_REUSED')
        return dict(cached['response'], replayed=True)
    record = service.repository.get(request['params'].get('document_id', '')) or {}
    receipt = service.repository.replay(record, request)
    if receipt and 'response' in receipt:
        result = response(request, service.inventory['revision'])
        result.update(receipt['response'], replayed=True)
        return result


def check_transfer_request(service, request):
    from ...core.authoring.codec import digest
    key = [service.inventory['root_id'] or service.inventory['scene_id'], request['request_id']]
    cached = service.store.get('v04_requests', key)
    require(not cached or cached['digest'] == digest(request), 'REQUEST_ID_REUSED')


def current_preview_cache(cached, request):
    if cached and request['op'] == 'anatomy.plan_fibers':
        plan = cached['response'].get('plan', {})
        if plan.get('version') != 'fiber_layout.v2' or not plan.get('native_solver_validated'):
            from ...core.authoring.codec import digest
            require(cached['digest'] == digest(request), 'REQUEST_ID_REUSED')
            return None
    return cached
