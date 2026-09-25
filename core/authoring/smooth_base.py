"""Coupled sparse patches and exact native loft previews; no routing solver."""
import numpy as np
from . import smooth_native as native
from .errors import require
from .smooth_extensions import attach
from ..vcp.fiber_surface import evaluate_fiber_surface, FiberSurfaceSpec


def construct(grids, controls, specs, aliases, hits, settings):
    count = settings.get('samples_per_fiber', 33); rows, output = {}, []
    for i, spec in enumerate(specs):
        for j in range(len(spec['endpoints'])):
            uv = np.c_[np.full(count, j/(len(spec['endpoints'])-1)), np.linspace(0, 1, count)]
            rows[i, j] = native.evaluate(controls[i], uv, linear=True)
            rows[i, j] = attach(rows[i, j], hits[i, j])
    for key, canonical in aliases.items(): rows[key] = rows[canonical]
    for i, spec in enumerate(specs):
        paths = [rows[i, j][0] for j in range(len(spec['endpoints']))]; stations = [rows[i, j][1].tolist() for j in range(len(spec['endpoints']))]
        output.append(part(i, spec, grids[i], controls[i], paths, stations, aliases, hits, settings))
    return output


def part(index, spec, grid, controls, rows, stations, aliases, hits, settings):
    surface = evaluate_fiber_surface(rows, FiberSurfaceSpec(exact_samples=True, parameter_stations=tuple(stations)))
    vertices = np.asarray(surface.vertices); quads = np.asarray(surface.faces)
    triangles = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]))
    shape = grid.shape[:2]; fitted = native.evaluate(controls, native.coordinates(*shape), linear=True).reshape(*shape, 3)
    fibers = [dict(key=list(aliases[index, j]), path=row.tolist(), stations=stations[j], endpoints=hits[index, j]) for j, row in enumerate(rows)]
    return dict(id=spec['id'], head_ids=spec['head_ids'], output_domain=spec.get('output_domain', dict(mode='full')), controls=controls.tolist(), fibers=fibers,
        base=dict(vertices=fitted.reshape(-1, 3).tolist(), triangles=native.faces(*shape).tolist()),
        native=dict(vertices=vertices.tolist(), triangles=triangles.tolist()),
        fit=fit_report(grid, fitted, controls, rows), rows=len(surface.rows), columns=len(surface.rows[0]))


def fit_report(grid, fitted, controls, rows):
    ids = np.rint(np.linspace(0, grid.shape[1]-1, 7)[1:-1]).astype(int)
    width = np.linalg.norm(grid[-1, ids]-grid[0, ids], axis=1)
    new = np.linalg.norm(fitted[-1, ids]-fitted[0, ids], axis=1)
    errors = np.linalg.norm(fitted-grid, axis=2)
    from ..vcp.free_surface import sample_at
    t = np.linspace(0, 1, 33); compared = [sample_at(row, t) for row in rows]
    ideal = [native.evaluate(controls, np.c_[np.full(len(t), j/(len(rows)-1)), t], linear=True) for j in range(len(rows))]
    return dict(rms=float(np.sqrt(np.mean(errors**2))), maximum=float(errors.max()),
        width_change=((new-width)/np.maximum(width, 1e-9)).tolist(),
        correspondence_shift=float(np.linalg.norm(np.asarray(compared)-ideal, axis=2).max()),
        correspondence='authored material stations; correspondence_shift reports the rejected arc-length mapping')
