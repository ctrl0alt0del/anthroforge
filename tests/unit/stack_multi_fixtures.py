"""Smooth deterministic material domains; no numerical optimization in Python."""
from dataclasses import replace
import numpy as np
from pair_fixtures import rectangle
from stack_fixture_adapter import payload
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.model import StackingSettings


def patch(name, bounds, z, height, n=19, pinned=False, group=None):
    side = rectangle(name, bounds, z, n=n)
    x0, x1, y0, y1 = bounds
    uv = (side.base[:, :2] - (x0, y0)) / (x1-x0, y1-y0)
    h = height * np.prod(np.sin(np.pi*uv)**2, axis=1)
    own = side.base.copy(); own[:, 2] += h
    pins = np.flatnonzero(np.any((uv < 1e-8) | (uv > 1-1e-8), axis=1)) if pinned else ()
    return payload(replace(side, own=own, family=group or name), pins)


def providers(disjoint=False, n=19):
    bounds = [(-1.5, -.15, -.8, .8), (.15, 1.5, -.8, .8)] if disjoint else [(-1.4, .5, -.8, .8), (-.5, 1.4, -.8, .8)]
    return [patch('provider_a', bounds[0], 0., .40, n, group='sibling_support'),
            patch('provider_b', bounds[1], .025, .44, n, group='sibling_support'),
            patch('cover', (-2, 2, -1.3, 1.3), .10, .055, n+8, True)]


def chain(n=19):
    return [patch('lower', (-1, 1, -.65, .65), 0., .38, n),
            patch('middle', (-1.5, 1.5, -1, 1), .07, .10, n+4, True),
            patch('top', (-2, 2, -1.3, 1.3), .14, .08, n+8, True)]


def settings(clearance=0., radius=.2, strength=.8, exclusions=()):
    return DetectionSettings(stacking=StackingSettings(clearance=clearance, radius=radius,
                                                     strength=strength, exclusions=exclusions))


def exclude(a, b):
    return tuple((d.key.muscle, d.key.instance, d.key.side) for d in (a, b))


def duplicate(values):
    a = values[0]
    return [*values, replace(a, key=replace(a.key, muscle='provider_a_duplicate'))]


def deepen(values, delta=.07):
    a = values[0]; own = a.base + (a.own-a.base)*(1+delta/.4)
    return [replace(a, own=own), *values[1:]]


def fixed_conflict(values):
    c = values[-1]; index = int(np.argmin(np.linalg.norm(c.base[:, :2]-(-.45, 0), axis=1)))
    pins = np.unique(np.append(c.material.fixed, index)).astype('int64')
    return [*values[:-1], replace(c, material=replace(c.material, fixed=pins))]
