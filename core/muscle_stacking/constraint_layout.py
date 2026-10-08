"""Replay canonical loft parameterization, retaining source-row addresses rather than spatial snapping."""
import numpy as np
from ..vcp import fiber_surface as loft
from ..vcp import free_surface as free
from ..vcp.free_surface_stations import resolve
from ..vcp.free_path import is_free, stations


def row_addresses(rows, minimum, densify=True):
    if not densify: return np.arange(len(rows), dtype=float)
    step = loft._average_row_step(rows)
    return np.r_[0, np.cumsum([loft._row_inserts(a, b, step, minimum)+1 for a, b in zip(rows, rows[1:])])]


def ordinary(source, fibers, rows, request):
    closed = request.spec.closed_u
    if any(is_free(f) for f in fibers): return free_layout(source, fibers, rows, closed)
    knots = [np.linspace(0, 1, len(r), endpoint=not closed) for r in rows]; across = np.arange(len(rows))
    if hasattr(source, 'construction_mode'):
        rows, knots, across = controlled_stage(rows, knots, across, request.spec.target_count, closed, True)
    grid, knots, across = controlled_stage(rows, knots, across, request.spec.target_count, closed, request.spec.densify)
    return across, np.linspace(0, 1, request.spec.target_count, endpoint=not closed), knots, np.asarray(grid)


def free_layout(source, fibers, rows, closed=False):
    authored = resolve(source, fibers)
    if closed: return free_closed(rows)
    knots = [np.asarray(s, float) for s in authored] if authored else [row_knots(r, False) for r in rows]
    target = np.unique(np.concatenate(knots))
    sampled = [np.column_stack([np.interp(target, s, np.asarray(r)[:, j]) for j in range(3)]).tolist() for r, s in zip(rows, knots)]
    minimum = 1 if len(rows) == 2 else 0
    across = row_addresses(sampled, minimum)
    return across, target, knots, np.asarray(loft._densify_rows(sampled, minimum))


def row_knots(row, closed):
    values = stations(np.vstack((row, np.asarray(row)[:1])) if closed else np.asarray(row))
    return values[:-1] if closed else values


def permutation(original, aligned):
    lookup = {tuple(p): i for i, p in enumerate(original)}
    if len(lookup) != len(original): raise ValueError('STACK_AMBIGUOUS_CYCLIC_SAMPLES')
    return np.asarray([lookup[tuple(p)] for p in aligned])


def free_closed(rows):
    aligned = free.align_closed_rows(rows); knots = []
    for original, row in zip(rows, aligned):
        order = permutation(original, row); values = np.empty(len(row))
        values[order] = row_knots(row, True); knots.append(values)
    target = free.union_stations(aligned, True)
    sampled = [free.sample_at(np.asarray(row), target, True).tolist() for row in aligned]
    return row_addresses(sampled, 3), target, knots, np.asarray(loft._densify_rows(sampled, 3))


def resampled_parameter(row, sampled, aligned, values, closed):
    knots = row_knots(row, closed)
    # Input values address the original material, never a nearest spatial point.
    v = np.interp(values, np.linspace(0, 1, len(row), endpoint=not closed), knots) if not closed else periodic(values, knots)
    if not closed: return v
    order = permutation(sampled, aligned); n = len(order)
    sign = 1 if (order[1]-order[0]) % n == 1 else -1
    return np.mod((v*n-order[0])*sign, n)/n


def periodic(values, knots):
    return np.interp(values, np.linspace(0, 1, len(knots)+1), np.r_[knots, 1.])


def controlled_stage(rows, knots, across, count, closed, densify):
    sampled = [loft._resample(r, count, closed) for r in rows]
    aligned = loft._align_closed_rows(sampled) if closed else sampled
    values = [resampled_parameter(rows[int(i)], sampled[int(i)], aligned[int(i)], k, closed) for i, k in zip(across, knots)]
    address = row_addresses(aligned, 3 if closed else 0, densify)
    prepared = loft._densify_rows(aligned, 3 if closed else 0) if densify else aligned
    return prepared, values, address[np.asarray(across, dtype=int)]
