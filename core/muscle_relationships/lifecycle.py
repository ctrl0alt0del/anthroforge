"""Relationship job adapter on the existing single-flight coordinator."""
from dataclasses import dataclass, replace
from contextlib import contextmanager
from time import perf_counter
from . import store, migration, fingerprints, policy, reconcile
from .validation import require


@dataclass(frozen=True)
class RelationshipJob:
    document: dict
    manifest: dict
    configuration: str
    generation: int


class RelationshipLifecycle:
    def prepare(self, scope):
        from .blender_identity import ensure_unique
        migration.ensure(scope[1]); ensure_unique(scope[1])

    def capture(self, scope, domains, settings, generation):
        from ..muscle_pairs import configuration
        start = perf_counter(); root = scope[1]; document = migration.ensure(root)
        manifest = fingerprints.manifest(domains, settings)
        captured = policy.capture(document, manifest, domains)
        job = RelationshipJob(document, manifest, configuration.inspect(root)['configuration_revision'], generation)
        stack = replace(settings.stacking, exclusions=()) if settings.stacking else None
        return replace(settings, relationships=captured, stacking=stack), job, {'fingerprint_ms': (perf_counter()-start)*1000}

    def guard(self, scope, job):
        from ..muscle_pairs import configuration, runtime
        root = scope[1]; current = store.read(root)
        require(current is not None and current['namespace'] == job.document['namespace'], 'RELATIONSHIP_NAMESPACE')
        require(current['revision'] == job.document['revision'], 'RELATIONSHIP_STALE_REVISION')
        require(configuration.inspect(root)['configuration_revision'] == job.configuration, 'STALE_CONFIGURATION_REVISION')
        require(runtime.COORDINATOR.inspect(runtime.key(*scope)).generation == job.generation, 'RELATIONSHIP_STALE_GENERATION')

    def publish(self, scope, job, backend, result, publisher):
        self.guard(scope, job); start = perf_counter()
        document = reconcile.reconcile(job.document, job.manifest, result)
        result['timings']['relationship_reconcile_ms'] = (perf_counter()-start)*1000
        publisher(scope, backend, result, commit=lambda: record_commit(scope[1], document, job.document['revision'], result),
            guard=lambda: self.guard(scope, job))


@contextmanager
def record_commit(root, document, expected, result):
    start = perf_counter()
    with store.transaction(root, document, expected):
        result['timings']['relationship_commit_ms'] = (perf_counter()-start)*1000
        yield
