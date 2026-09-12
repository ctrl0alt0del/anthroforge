"""Sparse hard controls correct measured solver failures, not surface curvature."""
import numpy as np
from .errors import require
from .layout_reduction import lengths, resample


def refine(reference, solve, tolerance, max_points, budget):
    reference = np.asarray(reference)
    indices, corrections, previous = [0, len(reference)-1], [], float('inf')
    while True:
        budget.check()
        result = solve(indices)
        error = route_error(reference, np.asarray(result['path']))
        record_error(corrections, error)
        if result['validated'] and error <= tolerance:
            return dict(result, indices=indices, corrections=corrections, route_max_error=error)
        require(error > tolerance, 'LAYOUT_ROUTE_UNSAFE', 'The native route failed validation; more hard points are not justified by route deviation.')
        require(error < previous-1e-8, 'LAYOUT_ROUTE_CORRECTION_STALLED', 'A routing correction did not improve the solved path.')
        indices, correction = add_correction(reference, result['path'], indices, max_points, error)
        corrections.append(correction)
        previous = error


def record_error(corrections, error):
    if corrections:
        corrections[-1]['after_error'] = error


def distances(points, path):
    a, edge = path[:-1], np.diff(path, axis=0)
    squared = np.einsum('ij,ij->i', edge, edge)
    delta = points[:, None]-a[None]
    projection = np.einsum('nij,ij->ni', delta, edge)
    t = np.divide(projection, squared, out=np.zeros_like(projection), where=squared > 1e-20)
    return np.linalg.norm(delta-np.clip(t, 0, 1)[:, :, None]*edge[None], axis=2).min(axis=1)


def route_error(reference, path):
    require(len(path) >= 2 and np.isfinite(path).all(), 'LAYOUT_ROUTE_UNAVAILABLE')
    target = np.concatenate((reference, (reference[:-1]+reference[1:])/2))
    actual = np.concatenate((path, (path[:-1]+path[1:])/2))
    return float(max(distances(target, path).max(), distances(actual, reference).max()))


def add_correction(reference, path, indices, max_points, error):
    require(len(indices) < max_points, 'LAYOUT_POINT_BUDGET', f'Route still deviates by {error:.5g}; the limit is {max_points-2} middle points. Review the route/support instead of tracing the surface.')
    target, actual = resample(reference, len(reference)), resample(np.asarray(path), len(reference))
    station = int(np.argmax(np.linalg.norm(target-actual, axis=1)))/(len(target)-1)
    available = np.setdiff1d(np.arange(1, len(reference)-1), indices)
    require(len(available) > 0, 'LAYOUT_POINT_BUDGET')
    index = int(available[np.argmin(abs(lengths(reference)[available]-station))])
    return sorted(indices+[index]), dict(sample_index=index, reason='solved_route_deviation', before_error=error)
