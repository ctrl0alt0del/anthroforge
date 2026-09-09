"""Static shape compilation and guarded native publication."""
from copy import deepcopy
from time import perf_counter
from functools import lru_cache
from pathlib import Path
from ...core.authoring.codec import digest
from ...core.authoring.errors import AuthoringError, require
from ...core.authoring.evaluation import evaluate_muscle, checked_result
from ...core.authoring.inspection import svg
from ...core.authoring.lowering import compile_document
from ...core.authoring.native_resolver import DomainResolver
from ...core.authoring.references import lookup
from ...core.authoring.fitting import fit
from . import queries
from .resources import EvaluationGuard, GuardedSolver

BACKEND = 'static-native-v3-material-0.4.0.1'


def compile(service, request):
    record = service.load(request['params'])
    service.check(request['params'], record)
    require(not record.get('local_overrides'), 'LOCAL_OVERRIDE_REQUIRES_RESOLUTION', 'Native edits are preserved; resolve their inverse mapping before regenerating.')
    result = queries.evaluation(service, record)
    if result['status'] != 'success':
        return result
    document = queries.resolved_document(service, record)
    ir = compile_document(document, service.inventory)
    compiled = evaluate(service, document, ir)
    saved = dict(compiled=compiled, state=compiled['state'])
    service.repository.finish(document['document_id'], record['draft_revision'], saved)
    return dict(status=compiled['state'], evaluation=compiled['report'], assets=compiled['assets'], draft_revision=record['draft_revision'])


def evaluate(service, document, ir):
    guard, snapshot, resolver = evaluation_context(service, document, ir)
    outputs, report, assets = {}, {}, []
    for name in ir['document']['muscles']:
        started = perf_counter()
        row = evaluate_one(service, document, ir, name, resolver, guard)
        report[name] = dict(state=row['state'], diagnostics=row['diagnostics'], cost_ms=(perf_counter()-started)*1000, cached=row.get('cached', False))
        if row.get('output'):
            guard.surface(len(row['output'].get('inflated', [])))
            outputs[name] = row['output']
            assets.extend([service.store.asset(row['output']), service.store.image(svg(snapshot, row['output'], name))])
    state = 'success' if all(r['state'] == 'success' for r in report.values()) else 'unresolved'
    return dict(state=state, ir=ir, source_digest=digest(document), scene_revision=service.inventory['revision'], outputs=outputs, report=report, assets=assets, backend=backend_version())


def evaluation_context(service, document, ir):
    guard = EvaluationGuard(service, document)
    guard.check()
    snapshot = service.scene.capture(service.inventory['scene_id'])
    resolver = DomainResolver(ir, document, snapshot, service.inventory)
    return guard, snapshot, resolver


def evaluate_one(service, document, ir, name, resolver, guard):
    key = digest([evaluation_key(service, ir, name), instance_shape(document, name), instance_value(document, name).get('route_overrides'), domain_inputs(ir, name, resolver)])
    cached = service.store.get('v04_evaluations', key)
    if cached:
        guard.fiber(len((cached.get('output') or {}).get('fibers', [])))
        return dict(cached, cached=True)
    try:
        output = native_evaluation(service, document, ir, name, resolver, guard)
        output = fit_checked(output, instance_shape(document, name), ir, name, resolver, guard)
        row = dict(state='success', output=output, diagnostics=[])
    except AuthoringError as error:
        row = evaluation_failure(error, locals().get('output'))
    service.store.put('v04_evaluations', key, row)
    return row


def native_evaluation(service, document, ir, name, resolver, guard):
    from ...core.authoring.routes import transform
    instance = instance_value(document, name)
    apply = (lambda plans: transform(instance, resolver, plans)) if instance.get('route_overrides') else None
    return evaluate_muscle(ir['document'], name, resolver, GuardedSolver(service.solver, guard), plan_transform=apply)


def evaluation_failure(error, output):
    transient = {'CANCELLED', 'TIME_BUDGET_EXHAUSTED', 'FIBER_BUDGET_EXHAUSTED', 'TOTAL_BUDGET_EXHAUSTED', 'SOLVER_BUDGET'}
    if error.code in transient:
        raise error
    return dict(state='unresolved', output=getattr(error, 'preview', output), diagnostics=[error.diagnostic()])


def fit_checked(output, shape, ir, name, resolver, guard=None):
    result = checked_result(fit(output, shape, guard), ir['document'], name, resolver)
    try:
        require(result['fitting']['state'] == 'resolved', 'SHAPE_TARGETS_UNRESOLVED')
        require(not result['contact']['area'], 'INFLATED_PENETRATION')
    except AuthoringError as error:
        error.preview = result
        raise
    return result


def evaluation_key(service, ir, name):
    document = ir['document']
    muscle = document['muscles'][name]
    regions = {k: document['regions'][k] for k in [v['region'] for v in muscle['region_bindings'].values()]}
    frames = {v['frame']: document['frames'][v['frame']] for v in regions.values()}
    targets = {v['owner']: document['targets'][v['owner']] for v in frames.values()}
    domain = {k: ir['domains'][k] for k in regions}
    inputs = [muscle, document['recipes'][muscle['recipe']], document['volume_presets'][muscle['volume_preset']], document['policies'][muscle['policy']], regions, frames, targets, domain]
    return digest([inputs, service.inventory['geometry'], backend_version()])


@lru_cache(maxsize=1)
def backend_version():
    import hashlib
    import numpy as np
    root = Path(__file__).resolve().parents[2]
    folders = ('core/authoring', 'core/vcp', 'core/visualization', 'adapters/authoring', 'app/authoring')
    files = sorted(p for folder in folders for p in (root/folder).rglob('*.py'))
    code = [(str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
    return BACKEND+'+'+digest([code, np.__version__])[:16]


def domain_inputs(ir, name, resolver):
    bindings = ir['document']['muscles'][name]['region_bindings'].values()
    return {v['region']: resolver.domains[v['region']] for v in bindings}


def instance_value(document, name):
    instance = document.get('instances', {}).get(name)
    if instance is None:
        matches = [row for key, assembly in document.get('assemblies', {}).items() for child, row in assembly['instances'].items() if key+'__'+child == name]
        require(len(matches) == 1, 'ASSEMBLY_INSTANCE_AMBIGUOUS')
        instance = matches[0]
    return instance


def instance_shape(document, name):
    return lookup(document, instance_value(document, name)['shape'])


def publish(service, request):
    record = service.load(request['params'])
    service.check(request['params'], record)
    compiled = record.get('compiled', {})
    require(compiled.get('state') == 'success', 'COMPILATION_UNRESOLVED')
    require(compiled['backend'] == backend_version(), 'STALE_BACKEND_COMPILATION')
    require(compiled['source_digest'] == digest(queries.resolved_document(service, record)), 'STALE_COMPILATION')
    require(compiled['scene_revision'] == service.inventory['revision'], 'STALE_COMPILATION')
    snapshot = service.scene.capture(service.inventory['scene_id'])
    with service.publication.publish(snapshot, compiled['ir']['document'], compiled['outputs'], record.get('published')) as ids:
        saved = dict(document=compiled['ir']['document'], authored_baseline=deepcopy(record['document']), native_ids=ids, scene_revision=service.scene.capture_authoring()['revision'])
        service.publication.persist(saved)
        saved['native_baseline'] = service.publication.owned_records(ids)
        result = finish_publication(service, request, record, saved)
    return result


def finish_publication(service, request, record, saved):
    from ...core.authoring.reviews import aggregate
    result = dict(published=True, native_ids=saved['native_ids'], scene_revision=saved['scene_revision'], anatomical_review=aggregate(queries.resolved_document(service, record), service.inventory))
    receipts = dict(record['receipts'])
    receipts[request['request_id']] = dict(digest=digest(request), revision=record['draft_revision'], state='published', response=result)
    service.repository.finish(record['document']['document_id'], record['draft_revision'], dict(published=saved, receipts=receipts))
    return result
