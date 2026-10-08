"""Prepared open-loft assembly. Junctions are solved sample IDs, never proximity welds."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class BranchInput:
    id: str
    boundary: int
    roots: tuple
    fibers: tuple
    width: float = .25
    fullness: float = 0.0
    stations: tuple = ()


@dataclass(frozen=True)
class PreparedBranch:
    connection: BranchInput
    grid: np.ndarray
    seam: np.ndarray
    across: np.ndarray
    along: np.ndarray
    source_across: tuple = ()


@dataclass(frozen=True)
class PreparedAssembly:
    main: np.ndarray
    along: np.ndarray
    branches: tuple
    flip: bool = False


def parameter(points):
    points = np.asarray(points, dtype=float)
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    if not np.isfinite(points).all() or lengths[-1] <= 1e-12:
        raise ValueError("Nonfinite or collapsed fiber")
    return lengths / lengths[-1]


def sample(points, knots, stations=()):
    points = np.asarray(points, dtype=float)
    source = correspondence(points, stations)
    return np.column_stack([np.interp(knots, source, points[:, axis]) for axis in range(3)])


def correspondence(points, stations=()):
    if len(stations) == 0: return parameter(points)
    values = np.asarray(stations, dtype=float)
    if values.shape != (len(points),) or not np.isfinite(values).all() or np.any(np.diff(values) <= 0):
        raise ValueError('FREE_CORRESPONDENCE_STATIONS')
    return (values-values[0])/(values[-1]-values[0])


def row_stations(rows, stations):
    if len(stations) not in (0, len(rows)): raise ValueError('FREE_CORRESPONDENCE_ROWS')
    return tuple(correspondence(row, stations[i] if len(stations) else ()) for i, row in enumerate(rows))


def unit(values):
    return values / np.maximum(1e-12, np.linalg.norm(values, axis=-1, keepdims=True))


def smooth(values):
    value = np.clip(values, 0., 1.)
    return value * value * (3. - 2. * value)


def validate_connections(main, branches):
    occupied, ids = {}, set()
    for branch in branches:
        if branch.id in ids or not branch.id or branch.boundary not in (0, -1):
            raise ValueError("Branches need unique IDs and an outer boundary fiber")
        ids.add(branch.id)
        _validate_roots(main[branch.boundary], branch)
        first, last = branch.roots[0], branch.roots[-1]
        if any(first <= b and last >= a for a, b in occupied.get(branch.boundary, ())):
            raise ValueError("Branch intervals must not overlap or share endpoints")
        occupied.setdefault(branch.boundary, []).append((first, last))


def _validate_roots(boundary, branch):
    roots = branch.roots
    if len(roots) < 2 or len(roots) != len(branch.fibers):
        raise ValueError("Every branch fiber requires an explicit main-fiber root")
    if any(type(i) is not int for i in roots) or tuple(sorted(set(roots))) != roots:
        raise ValueError("Root sample IDs must be strictly increasing")
    if roots[0] <= 0 or roots[-1] >= len(boundary) - 1:
        raise ValueError("Branch roots must lie inside the main boundary fiber")
    if not .0 < branch.width < .5 or not np.isfinite(branch.fullness):
        raise ValueError("Connector width must be between zero and one half; fullness must be finite")
    for index, row in zip(roots, branch.fibers):
        if not _shared_root_equal(boundary[index], row[0]):
            raise ValueError("Branch endpoint must equal its shared solved main point")


def _shared_root_equal(first, second):
    # Native Blender routes are float32; independently resolved uses may differ by a few ULPs.
    first, second = np.asarray(first), np.asarray(second)
    tolerance = np.maximum(1e-8, 4*np.spacing(np.abs(first).astype(np.float32)))
    return bool(np.all(np.abs(first-second) <= tolerance))


def prepare_assembly(main_fibers, branches, flip=False, across_count=17, main_stations=()):
    main = tuple(np.asarray(row, dtype=float) for row in main_fibers)
    if len(main) < 2 or any(row.ndim != 2 or row.shape[1] != 3 or len(row) < 2 for row in main):
        raise ValueError("Main loft requires at least two valid open fibers")
    validate_connections(main, branches)
    stations = row_stations(main, main_stations)
    along = np.unique(np.concatenate(stations))
    grid = _across_grid(np.array([sample(row, along, s) for row, s in zip(main, stations)]), across_count)
    prepared = tuple(_prepare_branch(main, grid, along, branch, stations) for branch in branches)
    return PreparedAssembly(grid, along, prepared, bool(flip))


def _across_grid(rows, count):
    source = np.linspace(0., 1., len(rows))
    target = np.unique(np.r_[source, np.linspace(0., 1., max(3, count))])
    flat = rows.reshape(len(rows), -1)
    return np.array([np.interp(target, source, col) for col in flat.T]).T.reshape(-1, *rows.shape[1:])


def _prepare_branch(main, grid, along, branch, stations):
    roots = stations[branch.boundary][list(branch.roots)]
    seam = np.flatnonzero((along >= roots[0]) & (along <= roots[-1]))
    across = (along[seam] - roots[0]) / (roots[-1] - roots[0])
    root_u = (roots - roots[0]) / (roots[-1] - roots[0])
    child_stations = row_stations(branch.fibers, branch.stations)
    longitudinal = np.unique(np.concatenate([np.linspace(0., 1., 17), *child_stations]))
    rows = np.array([sample(row, longitudinal, s) for row, s in zip(branch.fibers, child_stations)])
    flat = rows.reshape(len(rows), -1)
    result = np.array([np.interp(across, root_u, col) for col in flat.T]).T.reshape(len(across), -1, 3)
    correction = grid[branch.boundary, seam] - result[:, 0]
    result += correction[:, None] * (1 - smooth(longitudinal))[None, :, None]
    result[:, 0] = grid[branch.boundary, seam]
    return PreparedBranch(branch, result, seam, across, longitudinal, tuple(map(float, root_u)))


def quads(shape, flip=False):
    rows, cols = shape[:2]
    i, j = np.meshgrid(np.arange(rows-1), np.arange(cols-1), indexing="ij")
    a = (i * cols + j).ravel()
    faces = np.column_stack((a, a+cols, a+cols+1, a+1))
    return faces[:, ::-1] if flip else faces


def assemble(assembly, main=None, branches=None):
    main = assembly.main if main is None else main
    branches = tuple(b.grid for b in assembly.branches) if branches is None else branches
    if len(branches) != len(assembly.branches):
        raise ValueError("Missing prepared branch output")
    vertices, faces = [main.reshape(-1, 3)], [quads(main.shape, assembly.flip)]
    count = len(vertices[0])
    for prepared, grid in zip(assembly.branches, branches):
        mapping, additional = _branch_map(main, grid, prepared, count)
        vertices.append(additional); count += len(additional)
        flip = (prepared.connection.boundary == -1) != assembly.flip
        faces.append(mapping[quads(grid.shape, flip)])
    return np.concatenate(vertices), np.concatenate(faces)


def _branch_map(main, grid, branch, count):
    if grid.shape != branch.grid.shape or not np.array_equal(grid[:, 0], main[branch.connection.boundary, branch.seam]):
        raise ValueError("Prepared seam identity was lost")
    mapping = np.empty(grid.shape[:2], dtype=np.int64)
    boundary = len(main)-1 if branch.connection.boundary == -1 else 0
    mapping[:, 0] = boundary * main.shape[1] + branch.seam
    mapping[:, 1:] = np.arange(count, count + grid[:, 1:].size//3).reshape(mapping[:, 1:].shape)
    return mapping.ravel(), grid[:, 1:].reshape(-1, 3)
