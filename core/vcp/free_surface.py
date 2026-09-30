"""Bounded union sampling preserves every corner of Free-containing lofts."""
import numpy as np
from .free_path import stations

MAX_STATIONS = 16384
MAX_VERTICES = 262144
MAX_TRIANGLES = 524288


def check_budget(vertices, triangles, multiplier=1):
    vertices, triangles = int(vertices) * multiplier, int(triangles) * multiplier
    if vertices > MAX_VERTICES or triangles > MAX_TRIANGLES:
        raise ValueError(f'FREE_OUTPUT_BUDGET: {vertices} vertices / {triangles} triangles; limits {MAX_VERTICES}/{MAX_TRIANGLES}.')


def union_stations(rows, closed=False, extra=()):
    values = [stations(np.vstack((row, row[:1])) if closed else np.asarray(row)) for row in rows]
    target = np.unique(np.concatenate((*values, np.asarray(extra))))
    if closed: target = target[target < 1]
    if len(target) > MAX_STATIONS: raise ValueError(f'FREE_STATION_BUDGET: {len(target)} > {MAX_STATIONS}.')
    return target


def sample_at(points, target, closed=False):
    rows = np.vstack((points, points[:1])) if closed else np.asarray(points)
    source = stations(rows)
    return np.column_stack([np.interp(target, source, rows[:, axis]) for axis in range(3)])


def prepare_rows(rows, closed=False, densify=True, multiplier=1):
    from .fiber_surface import _average_row_step, _row_inserts, _densify_rows
    rows = align_closed_rows(rows) if closed else rows
    target = union_stations(rows, closed)
    check_budget(len(rows) * len(target), 2 * (len(rows) - 1) * len(target), multiplier)
    prepared = [sample_at(np.asarray(row), target, closed).tolist() for row in rows]
    step = _average_row_step(prepared)
    minimum = 3 if closed else int(len(prepared) == 2)
    inserts = sum(_row_inserts(a, b, step, minimum) for a, b in zip(prepared, prepared[1:])) if densify else 0
    count = len(rows) + inserts
    check_budget(count * len(target), 2 * (count - 1) * len(target), multiplier)
    return _densify_rows(prepared, minimum) if densify else prepared


def align_closed_rows(rows):
    output = [np.asarray(rows[0]).copy()]
    for row in rows[1:]:
        reference = output[-1]; row = np.asarray(row)
        target = stations(np.vstack((reference, reference[:1])))[:-1]
        candidates = (np.roll(values, -i, axis=0) for values in (row, row[::-1]) for i in range(len(row)))
        output.append(min(candidates, key=lambda candidate: float(np.square(sample_at(candidate, target, True) - reference).sum())))
    return output


def branch_budget(main, branches, across_count=17, multiplier=1):
    along = union_stations(main); across = len(np.unique(np.r_[np.linspace(0, 1, len(main)), np.linspace(0, 1, across_count)]))
    vertices, triangles = across * len(along), 2 * (across - 1) * (len(along) - 1)
    for branch in branches:
        roots = stations(np.asarray(main[branch.boundary]))[list(branch.roots)]
        width = np.count_nonzero((along >= roots[0]) & (along <= roots[-1]))
        length = len(union_stations(branch.fibers, extra=np.linspace(0, 1, 17)))
        vertices += width * (length - 1); triangles += 2 * (width - 1) * (length - 1)
    check_budget(vertices, triangles, multiplier)
    return vertices, triangles
