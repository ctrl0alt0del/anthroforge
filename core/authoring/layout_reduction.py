"""Finite shortcut graphs for a sampled ruled-strip envelope.

Minimum fiber count is exact only for fixed candidates and these band tests.
Dense guide samples measure shape; they are never converted to hard touches here.
"""
import numpy as np
from .errors import require
from .model import Budget


def lengths(points):
    values = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    require(values[-1] > 1e-10, 'LAYOUT_DEGENERATE_ROUTE')
    return values/values[-1]


def interpolate(points, positions, targets):
    return np.column_stack([np.interp(targets, positions, points[:, axis]) for axis in range(3)])


def resample(points, count):
    return interpolate(points, lengths(points), np.linspace(0, 1, count))


def shortest_path(count, admissible, costs=None):
    costs = costs if costs is not None else [0]*count
    best, previous = [(float('inf'), float('inf'))]*count, [-1]*count
    best[0] = (1, costs[0])
    for j in range(1, count):
        for i in range(j):
            candidate = (best[i][0]+1, best[i][1]+costs[j])
            if candidate < best[j] and admissible(i, j):
                best[j], previous[j] = candidate, i
    require(previous[-1] >= 0, 'LAYOUT_TOLERANCE_UNREACHABLE', 'Increase sampling/point budgets or relax tolerance; no candidate path passes.')
    path = [count-1]
    while path[-1] != 0:
        path.append(previous[path[-1]])
    return list(reversed(path))


def strip_points(first, last, u, t, low, high):
    stations = np.linspace(0, 1, len(first))
    a, b = interpolate(first, stations, t), interpolate(last, stations, t)
    return a+((u-low)/(high-low))[:, None]*(b-a)


def band_error(rows, across, cloud, i, j):
    uv, target = cloud
    selected = (uv[:, 0] >= across[i]-1e-10) & (uv[:, 0] <= across[j]+1e-10)
    u, t = uv[selected].T
    prediction = strip_points(rows[i], rows[j], u, t, across[i], across[j])
    return float(np.max(np.linalg.norm(prediction-target[selected], axis=1)))


def select_fibers(routes, across, cloud, tolerance, max_fibers, max_points, budget=None):
    budget = budget or Budget()
    eligible = [len(route['points']) <= max_points for route in routes]
    require(eligible[0] and eligible[-1], 'LAYOUT_POINT_BUDGET', 'Boundary routes need more points at this tolerance.')
    rows, errors = [route['row'] for route in routes], {}
    for i in range(len(rows)-1):
        budget.check()
        for j in range(i+1, len(rows)):
            if eligible[i] and eligible[j]:
                errors[i, j] = band_error(rows, across, cloud, i, j)
    chosen = shortest_path(len(rows), lambda i, j: errors.get((i, j), float('inf')) <= tolerance, [len(r['points']) for r in routes])
    require(len(chosen) <= max_fibers, 'LAYOUT_FIBER_BUDGET', f'The sampled model needs {len(chosen)} fibers; max_fibers is {max_fibers}.')
    bands = [dict(first=i, last=j, max_error=errors[i, j]) for i, j in zip(chosen, chosen[1:])]
    return chosen, bands
