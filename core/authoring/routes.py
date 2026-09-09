"""Explicit portable route overrides retain native attachment corrections."""
from dataclasses import replace
from .errors import require
from .lowering import identity


def transform(instance, resolver, plans):
    overrides = instance.get('route_overrides', {})
    require(set(overrides) <= {p.id for p in plans}, 'ROUTE_OVERRIDE_STALE')
    return tuple(override(p, overrides[p.id], instance, resolver) if p.id in overrides else p for p in plans)


def override(plan, specification, instance, resolver):
    rows = specification['anchors']
    require(len(rows) == len(plan.anchors), 'ROUTE_OVERRIDE_TOPOLOGY_CHANGED')
    require(all(r['region'] in instance['bindings'].values() for r in rows), 'ROUTE_OVERRIDE_ROLE_MISSING')
    anchors = tuple(resolver.direct_anchor(identity(r['region']), r['seed'], r['offset']) for r in rows)
    require(all(a.owner == b.owner for a, b in zip(anchors, plan.anchors)), 'ROUTE_OVERRIDE_OWNER_CHANGED')
    return replace(plan, anchors=anchors)
