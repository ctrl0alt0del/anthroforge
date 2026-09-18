"""Native inflation on already welded grids, with explicit exterior boundary masks."""
from dataclasses import replace
from heapq import heappop, heappush
from functools import lru_cache
import numpy as np
from .branched_surface import smooth
from .muscle_numeric import _InflationAdapter, _initialized_spec


def boundary_masks(assembly):
    main = _perimeter(assembly.main.shape[:2])
    branches = []
    for branch in assembly.branches:
        main[branch.connection.boundary, branch.seam[1:-1]] = False
        mask = _perimeter(branch.grid.shape[:2])
        mask[1:-1, 0] = False
        branches.append(mask)
    return (main, *branches)


def _perimeter(shape):
    mask = np.zeros(shape, dtype=bool)
    mask[[0, -1], :] = True
    mask[:, [0, -1]] = True
    return mask


def boundary_distances(grid, fixed):
    if fixed.size > 100000:
        return _distance_field(grid, fixed)
    shape = tuple(fixed.shape)
    return _cached_distances(shape, np.asarray(grid, dtype=np.float64).tobytes(), fixed.tobytes())


@lru_cache(maxsize=16)
def _cached_distances(shape, coordinates, perimeter):
    grid = np.frombuffer(coordinates, dtype=np.float64).reshape((*shape, 3))
    fixed = np.frombuffer(perimeter, dtype=bool).reshape(shape)
    result = _distance_field(grid, fixed)
    result.setflags(write=False)
    return result


def _distance_field(grid, fixed):
    distances = np.full(fixed.shape, np.inf)
    distances[fixed] = 0.
    pending = [(0., int(i), int(j)) for i, j in np.argwhere(fixed)]
    while pending:
        distance, i, j = heappop(pending)
        if distance != distances[i, j]:
            continue
        for a, b in _neighbors(i, j, fixed.shape):
            candidate = distance + np.linalg.norm(grid[a, b] - grid[i, j])
            if candidate < distances[a, b]:
                distances[a, b] = candidate
                heappush(pending, (candidate, a, b))
    return distances


def _neighbors(i, j, shape):
    return ((a, b) for a, b in ((i-1, j), (i+1, j), (i, j-1), (i, j+1))
            if 0 <= a < shape[0] and 0 <= b < shape[1])


def weights(grid, fixed, spec, branch=False):
    lengths = np.r_[np.linalg.norm(np.diff(grid, axis=0), axis=2).ravel(),
                    np.linalg.norm(np.diff(grid, axis=1), axis=2).ravel()]
    step = max(float(np.mean(lengths)), 1e-12)
    distance = boundary_distances(grid, fixed) / (step * max(.1, spec.inflation_boundary_band))
    edge = 1-spec.inflation_boundary_strength + spec.inflation_boundary_strength*smooth(distance)**spec.inflation_boundary_power
    edge[fixed] = 0.
    along = np.column_stack((np.zeros(len(grid)), np.cumsum(np.linalg.norm(np.diff(grid, axis=1), axis=2), axis=1)))
    end = along[:, -1:]
    fade = end-along if branch else np.minimum(along, end-along)
    fade = smooth(fade/np.maximum(end*spec.inflation_length_taper_band, 1e-12))
    return np.ascontiguousarray(edge), np.ascontiguousarray(fade)


class PreparedAdapter(_InflationAdapter):
    def __init__(self, spec, edge, fade):
        super().__init__(spec)
        self.boundary_weights, self.length_weights = edge, fade


def validate_prepared_mode(mode):
    if mode == "SECTION_PROFILE":
        raise ValueError("PROFILE_DOMAIN_UNSUPPORTED: Section Profile requires an ordinary open loft.")
    if mode not in ("CTRL_POINT", "DISTRIBUTED"):
        raise ValueError("PROFILE_MODE_UNSUPPORTED: " + str(mode))


def inflate_prepared(grid, fixed, spec, backend="NATIVE", branch=False):
    validate_prepared_mode(spec.inflation_mode)
    edge, fade = weights(grid, fixed, spec, branch)
    if backend == "NATIVE":
        from .prepared_inflation_native import inflate_native
        return inflate_native(grid, spec, edge, fade)
    if backend != "PYTHON":
        raise ValueError("Unknown prepared inflation backend")
    from mathutils import Vector
    from ..visualization.muscle_inflation import apply_inflation_distributed, apply_inflation_from_ctrl
    points = [[Vector(p) for p in row] for row in grid]
    adapter = PreparedAdapter(_initialized_spec(points, spec), edge, fade)
    method = apply_inflation_distributed if spec.inflation_mode == "DISTRIBUTED" else apply_inflation_from_ctrl
    return np.asarray(method(points, adapter), dtype=float)


def inflate_assembly(assembly, specs, backend="NATIVE"):
    if len(specs) != len(assembly.branches)+1:
        raise ValueError("Each prepared part needs inflation settings")
    for spec in specs: validate_prepared_mode(spec.inflation_mode)
    grids = (assembly.main, *(b.grid for b in assembly.branches))
    reversals = (assembly.flip, *(assembly.flip != (b.connection.boundary == -1) for b in assembly.branches))
    values = []
    for index, (grid, mask, spec, flip) in enumerate(zip(grids, boundary_masks(assembly), specs, reversals)):
        oriented = replace(spec, flip_normals=flip)
        values.append(inflate_prepared(grid, mask, oriented, backend, index > 0))
    _share_displacements(assembly, values)
    from .branch_connector import connect
    return connect(assembly, values[0], values[1:])


def _share_displacements(assembly, values):
    for index, branch in enumerate(assembly.branches, 1):
        side, seam = branch.connection.boundary, branch.seam
        base = assembly.main[side, seam]
        displacement = .5*((values[0][side, seam]-base)+(values[index][:, 0]-base))
        displacement[[0, -1]] = 0.
        values[0][side, seam] = base + displacement
        values[index][:, 0] = values[0][side, seam]
