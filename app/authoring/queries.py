"""Compact read operations with content-addressed inspection geometry."""
from ...core.authoring.errors import AuthoringError
from ...core.authoring.requirements import RequirementResolver
from ...core.authoring.regions import RegionEvaluator
from ...core.authoring.preview import svg
from ...core.authoring.packages import expand
from ...core.authoring.references import graph


def resolved_document(service, record):
    return expand(record['document'], service.store.directory / 'packages')


def discover(service, request):
    from .service import operations, capabilities
    from .catalog import summary
    inventory = {k: v for k, v in service.inventory.items() if k not in ('geometry', 'native')}
    return dict(inventory=inventory, catalog=summary(service), capabilities=capabilities(), operations=sorted(operations()), assets=[service.store.asset(service.inventory)], unsupported=['feature_detection', 'reference_transfer', 'motion_simulation', 'arbitrary_mesh_transfer'])


def query(service, request):
    document = resolved_document(service, service.load(request['params']))
    spec = request['params']['query']
    if spec['kind'] == 'region':
        output = RegionEvaluator(document, service.inventory).evaluate(spec['reference'])
        return dict(matches=[dict(reference=spec['reference'], area=output['area'], limitations=output['limitations'])], assets=[service.store.asset(output), service.store.image(svg(output['polygons'], spec['reference']))])
    if spec['kind'] == 'entities':
        matches = entity_matches(document, spec)
    else:
        matches = [dict(reference='/relations/'+k, **v) for k, v in document.get('relations', {}).items() if v['subject'] == spec['subject']]
    return dict(matches=matches)


def entity_matches(document, spec):
    from ...core.authoring.records import read_records
    return [dict(reference='/entities/'+row.id, **document['entities'][row.id]) for row in read_records(document, 'entities') if row.concept == spec['concept'] and row.side == spec['side']]


def requirements(service, request):
    record = service.load(request['params'])
    return evaluation(service, record)


def evaluation(service, record):
    from .service import capabilities
    try:
        document = resolved_document(service, record)
        report = RequirementResolver(document, service.inventory, capabilities(), record.get('provisional', [])).report()
        missing = sorted(set(document.get('requires', []))-set(capabilities()))
        return dict(status='success' if report['resolved'] and not missing else 'unresolved', evaluation=report, unsupported=missing)
    except AuthoringError as error:
        return dict(status='unresolved', diagnostics=[error.diagnostic()])


def export(service, request):
    record = service.load(request['params'])
    return dict(document=record['document'], draft_revision=record['draft_revision'], assets=[service.store.asset(record)], state=record['state'])


def inspect(service, request):
    record = service.load(request['params'])
    document = resolved_document(service, record)
    assets, diagnostics = [], []
    for name, profile in document.get('skeleton_profiles', {}).items():
        for key in profile['regions']:
            reference = '/skeleton_profiles/'+name+'/regions/'+key
            try:
                output = RegionEvaluator(document, service.inventory).evaluate(reference)
                assets.extend([service.store.asset(output), service.store.image(svg(output['polygons'], key))])
            except AuthoringError as error:
                diagnostics.append(error.diagnostic())
    return dict(assets=assets, diagnostics=diagnostics, draft_revision=record['draft_revision'], status='unresolved' if diagnostics else 'success')


def explain(service, request):
    record = service.load(request['params'])
    result = evaluation(service, record)
    result['dependencies'] = {k: sorted(v) for k, v in graph(resolved_document(service, record)).items()}
    result['provenance'] = record.get('adoptions', [])
    return result


def validate(service, request):
    from ...core.authoring.reviews import aggregate
    record = service.load(request['params'])
    result = evaluation(service, record)
    result['purpose'] = 'static_avatar'
    result['anatomical_review'] = aggregate(resolved_document(service, record), service.inventory)
    result['scenarios'] = static_scenarios(service, resolved_document(service, record))
    return result


def static_scenarios(service, document):
    from .construction import evaluate
    from ...core.authoring.lowering import compile_document
    from ...core.authoring.variants import apply_variant
    result = {}
    for name, scenario in document.get('scenarios', {}).items():
        try:
            detached = apply_variant(document, scenario)
            output = evaluate(service, detached, compile_document(detached, service.inventory))
            result[name] = dict(state=output['state'], report=output['report'], assets=output['assets'])
        except AuthoringError as error:
            result[name] = dict(state='unresolved', diagnostics=[error.diagnostic()])
    return result


def compare(service, request):
    from .previews import compare as previews
    params = request['params']
    first = service.load(params)
    second = service.load(dict(document_id=params['other_document_id']))
    return dict(first=evaluation(service, first), second=evaluation(service, second), comparison_assets=[service.store.asset(first.get('compiled', {})), service.store.asset(second.get('compiled', {}))]+previews(service.store, first, second))
