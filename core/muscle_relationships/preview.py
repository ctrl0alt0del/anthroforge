"""Pure policy preview configuration; no identity or document publication."""
from copy import deepcopy
from dataclasses import replace
from . import store, changes, fingerprints, policy, migration


def configure(root, change, domains, settings):
    document = deepcopy(store.read(root))
    if document is None:
        if change.get('relationships'): raise ValueError('RELATIONSHIP_NOT_FOUND')
        return settings
    manifest = fingerprints.manifest(domains, settings)
    if 'exclusions' in change: document = migration.with_exclusions(document, change['exclusions'])
    document = changes.apply(document, change.get('relationships', []), manifest, domains)
    captured = policy.capture(document, manifest, domains)
    return replace(settings, relationships=captured, stacking=replace(settings.stacking, exclusions=()))
