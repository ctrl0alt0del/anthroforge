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
    anchors = tuple(route_anchor(resolver, row) for row in rows)
    require(all(a.owner == b.owner for a, b in zip(anchors, plan.anchors)), 'ROUTE_OVERRIDE_OWNER_CHANGED')
    return replace(plan, anchors=anchors)


def route_anchor(resolver, row):
    name = identity(row['region'])
    if 'surface_binding' in row:
        return resolver.bound_anchor(name, row['surface_binding'], row.get('offset', 0))
    return resolver.direct_anchor(name, row['seed'], row.get('offset', 0))
