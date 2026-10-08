"""Exact content serialization; all numerical geometry remains native."""
from dataclasses import asdict
from hashlib import sha256
import json
import numpy as np
from .identity import token

ALGORITHM = 'base-ray-vector-localized-policy-3'


def digest(value):
    return sha256(token(value).encode()).hexdigest()


def array(value):
    data = np.ascontiguousarray(value, dtype=np.asarray(value).dtype.newbyteorder('<'))
    return digest((data.dtype.str, data.shape, sha256(data.tobytes()).hexdigest()))


def key(domain):
    return (domain.key.muscle, domain.key.instance, domain.key.side)


def domain_stamp(domain, obstacles=None):
    topology = digest([array(v) for v in (domain.faces, domain.parts, domain.sources)])
    order = digest((topology, array(domain.base), array(domain.direction), domain.group, domain.enabled, domain.valid))
    material = domain.material
    constraints = digest([array(getattr(material, k)) for k in ('vertices', 'faces', 'interpolation', 'weights', 'fixed')])
    constraints = digest((constraints, [asdict(c) for c in material.constraints]))
    if obstacles is None: obstacles = obstacle_stamp(domain.obstacles, {})
    return dict(topology=topology, order=order, own=array(domain.own), material=constraints,
        allowance=domain.displacement, obstacles=obstacles)


def obstacle_stamp(obstacles, memo):
    key = tuple((id(b.vertices), id(b.faces)) for b in obstacles)
    if key not in memo: memo[key] = digest([(array(b.vertices), array(b.faces)) for b in obstacles])
    return memo[key]


def manifest(domains, settings, version=ALGORITHM):
    canonical = json.loads(token(asdict(settings)))
    memo = {}
    return dict(version=version, settings=canonical, domains={token(key(d)):
        domain_stamp(d, obstacle_stamp(d.obstacles, memo)) for d in domains})


def changed(before, after):
    old, new, result = before.get('domains', {}), after['domains'], {}
    for identity in old.keys() | new.keys():
        result[identity] = ['added'] if identity not in old else ['removed'] if identity not in new else [
            k for k in new[identity] if old[identity][k] != new[identity][k]]
    return {k: v for k, v in result.items() if v}


def affected(changes, records):
    dirty = set(changes)
    for _ in range(len(records) + 1):
        previous = len(dirty)
        for row in records.values():
            edge = row.get('effective_order') or row
            if edge.get('underlying'):
                underlying, cover = edge['underlying'], edge['covering']
                if isinstance(underlying, dict): underlying, cover = key_record(underlying), key_record(cover)
                if token(underlying) in dirty: dirty.add(token(cover))
        if len(dirty) == previous: break
    return sorted(dirty)


def key_record(value):
    return [value[k] for k in ('muscle', 'instance', 'side')]
