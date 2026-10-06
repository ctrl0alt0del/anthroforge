"""Existing inflation on exact prepared Free-containing grids (no resampling)."""
from time import perf_counter
import numpy as np


def execute(requests, kind, ordinary):
    from .muscle_numeric import MuscleNumericBatchResult
    start = perf_counter(); controlled = tuple(r for r in requests if not r.spec.preserve_samples)
    batch = ordinary(controlled) if controlled else None
    results = {id(r): value for r, value in zip(controlled, batch.results if batch else ())}
    for request in requests:
        if request.spec.preserve_samples: results[id(request)] = evaluate(request, kind)
    return MuscleNumericBatchResult(tuple(results[id(r)] for r in requests), kind,
                                    (perf_counter() - start) * 1000, batch.workers if batch else 1)


def evaluate(request, kind):
    from .muscle_numeric import _invalid_result
    try: return _evaluate(request, kind)
    except (ValueError, RuntimeError) as error: return _invalid_result(request.muscle_id, str(error))


def _evaluate(request, kind):
    from .muscle_numeric import _inflate_grid, _valid_result
    from .fiber_surface import build_loft_topology
    from .free_surface import check_budget
    from mathutils import Vector
    grid = request.points; spec = request.spec
    check_budget(grid.shape[0] * grid.shape[1], 2 * grid.shape[0] * grid.shape[1], 4)
    if spec.initialize_control:
        from dataclasses import replace
        spec = replace(spec, control_world=tuple(Vector(grid[len(grid)//2, len(grid[0])//2])))
    if kind == 'NATIVE': inflated = _native(grid, spec)
    else: inflated = _inflate_grid([[Vector(p) for p in row] for row in grid], spec)
    faces = build_loft_topology(*grid.shape[:2], spec.close_across_fibers, spec.closed_u, spec.topology_flip_normals)
    return _valid_result(request.muscle_id, grid, inflated, faces)


def _native(grid, spec):
    if not spec.inflation_enabled: return np.array(grid, copy=True)
    from .prepared_inflation_native import inflate_native
    from ..visualization.muscle_inflation import _edge_alpha, _length_fade, _inflation_params
    from .muscle_numeric import _InflationAdapter
    adapter = _InflationAdapter(spec); params = _inflation_params(adapter); m, n = grid.shape[:2]
    edge = np.array([[_edge_alpha(i, j, m, n, adapter, params['b_strength'], params['b_band'], params['b_power'])
                      for j in range(n)] for i in range(m)], dtype=float)
    fade = np.tile([_length_fade(j, n, params['length_taper_band']) for j in range(n)], (m, 1))
    return inflate_native(grid, spec, np.ascontiguousarray(edge), np.ascontiguousarray(fade))
