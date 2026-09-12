"""Read-only surface-region layout, independent of Blender and native creation."""
import numpy as np
from . import layout_patch, layout_chart, layout_reduction as reduction
from .errors import require
from .model import Budget


def plan(polygons, corners, tolerance, candidate_count=17, samples_per_fiber=65, max_fibers=65, max_points_per_fiber=4, audit=None, budget=None):
    budget = budget or Budget()
    require(np.isfinite(tolerance) and tolerance > 0, 'LAYOUT_INVALID_TOLERANCE')
    require(3 <= candidate_count <= 65 and 5 <= samples_per_fiber <= 129, 'LAYOUT_SAMPLE_BUDGET')
    patch, indices, across, along, grid = prepare(polygons, corners, candidate_count, samples_per_fiber, budget)
    routes = [dict(points=row[[0, -1]], row=reduction.resample(row, len(row)), reference=row) for row in grid]
    cloud = audit_cloud(patch, grid, across, along)
    chosen, bands = reduction.select_fibers(routes, across, cloud, tolerance, max_fibers, max_points_per_fiber, budget)
    result = summarize(routes, chosen, bands, across, cloud, tolerance)
    result.update(boundary_points=patch['vertices'][indices].tolist(), candidate_count=candidate_count, samples_per_fiber=samples_per_fiber)
    if audit is not None:
        audit.update(routes=routes, across=across, cloud=cloud)
    return result


def prepare(polygons, corners, candidate_count, samples_per_fiber, budget):
    budget.check()
    patch = layout_patch.mesh(polygons)
    indices = layout_chart.landmark_vertices(patch, corners)
    layout_chart.parameterize(patch, indices)
    across, along = np.linspace(0, 1, candidate_count), np.linspace(0, 1, samples_per_fiber)
    coordinates = np.array([(u, t) for u in across for t in along])
    grid = layout_chart.sample(patch, coordinates, budget).reshape(candidate_count, samples_per_fiber, 3)
    return patch, indices, across, along, grid


def recheck(result, audit):
    rows = [route['row'] for route in audit['routes']]
    for fiber in result['fibers']:
        rows[fiber['candidate_index']] = reduction.resample(np.asarray(fiber['solved_path']), result['samples_per_fiber'])
    for band in result['bands']:
        band['max_error'] = reduction.band_error(rows, audit['across'], audit['cloud'], band['first'], band['last'])
    result['max_sampled_error'] = max(b['max_error'] for b in result['bands'])
    require(result['max_sampled_error'] <= result['tolerance'], 'LAYOUT_SOLVED_ENVELOPE', 'Solved fibers exceed the sampled envelope tolerance; revise the area/layout or tolerance, rather than tracing it with more touches.')


def audit_cloud(patch, grid, across, along):
    faces = patch['faces']
    uv = np.concatenate((patch['uv'], patch['uv'][faces].mean(axis=1)))
    points = np.concatenate((patch['vertices'], patch['vertices'][faces].mean(axis=1)))
    mapped = arc_coordinates(uv, grid, across, along)
    targets = np.concatenate([reduction.resample(row, len(along)) for row in grid])
    stations = np.array([(u, t) for u in across for t in along])
    return np.concatenate((mapped, stations)), np.concatenate((points, targets))


def arc_coordinates(uv, grid, across, along):
    j = np.clip(np.searchsorted(across, uv[:, 0], side='right')-1, 0, len(across)-2)
    fraction = (uv[:, 0]-across[j])/(across[j+1]-across[j])
    samples = np.stack([np.interp(uv[:, 1], along, reduction.lengths(row)) for row in grid])
    columns = np.arange(len(uv))
    t = (1-fraction)*samples[j, columns]+fraction*samples[j+1, columns]
    return np.column_stack((uv[:, 0], t))


def summarize(routes, chosen, bands, across, cloud, tolerance):
    fibers = [dict(candidate_index=i, across=float(across[i]), points=routes[i]['points'].tolist(), reference_path=routes[i]['reference'].tolist()) for i in chosen]
    counts = [len(fiber['points']) for fiber in fibers]
    return dict(version='fiber_layout.v2', fibers=fibers, fiber_count=len(fibers), point_count=sum(counts),
                middle_point_count=sum(count-2 for count in counts), bands=bands, tolerance=tolerance,
                max_sampled_error=max(b['max_error'] for b in bands), audit_sample_count=len(cloud[0]),
                error_model='sampled_arc_length_ruled_strip.v1', minimum_scope='reference_candidates_only_native_routes_checked_after_selection',
                native_solver_validated=False, limitations=limitations())


def limitations():
    return ['One disk-shaped region on one SCP; four distinct boundary vertices define direction.',
            'Error is sampled positional deviation, not certified area coverage or Hausdorff distance.',
            'Fiber count is minimal only for the fixed surface guides; solved routes are checked afterward.',
            'Dense guide/solver samples are not hard anchors. Start with endpoints; add few touches only after a demonstrated solved-route deviation.',
            'The pure geometric proposal requires native route validation. Loft triangulation, inflation and anatomical acceptance remain separate.',
            'Bindings follow unchanged vertex indices; deforming the support requires replanning to reassess shape error.']
