"""One guarded intent mutation path for UI and authoring."""
from contextlib import contextmanager
from . import store, migration, changes, fingerprints
from .validation import require


def inputs(scope, expected_result=None):
    from ..muscle_pairs import runtime
    entry = runtime.COORDINATOR.entries.get(runtime.key(*scope))
    revision = f'{runtime.COORDINATOR.epoch}:{entry.generation}' if entry else None
    require(entry is not None and entry.result.status in ('complete', 'incomplete'), 'RELATIONSHIP_RESULT_NOT_READY')
    require(expected_result is None or expected_result == revision, 'PAIR_STALE_RESULT')
    require(entry.backend is not None, 'RELATIONSHIP_RESULT_NOT_READY')
    return tuple(entry.backend.domains.values()), entry.settings


def prepare(scope, change, expected, expected_result):
    from ..muscle_pairs import configuration
    root = scope[1]; document = migration.ensure(root); rows = change.get('relationships', [])
    require(expected is not None and expected == document['revision'], 'RELATIONSHIP_STALE_REVISION')
    region = any(row.get('region') is not None for row in rows)
    require(not region or expected_result is not None, 'RELATIONSHIP_RESULT_REVISION_REQUIRED')
    domains, settings = inputs(scope, expected_result) if region else ((), configuration.settings(root))
    manifest = fingerprints.manifest(domains, settings) if region else document['manifest']
    return changes.apply(document, rows, manifest, domains), document['revision']


@contextmanager
def mutation(scope, change, expected=None, expected_result=None):
    from ..muscle_pairs import configuration
    from contextlib import nullcontext
    root = scope[1]; numeric = {k: v for k, v in change.items() if k != 'relationships'}
    require(not ('relationships' in change and 'exclusions' in change), 'RELATIONSHIP_DUPLICATE_CONFIGURATION')
    with migration.rollback(root):
        value, revision = prepare(scope, change, expected, expected_result) if 'relationships' in change else (None, None)
        with configuration.transaction(root, numeric):
            with store.transaction(root, value, revision) if value is not None else nullcontext(): yield


def configure(scope, change, expected=None, expected_result=None):
    from ..muscle_pairs import runtime
    with mutation(scope, change, expected, expected_result): pass
    runtime.refresh(*scope, explicit=True)
