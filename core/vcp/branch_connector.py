"""Local Hermite replacement using retained-side tangents and geometric spacing."""
import numpy as np
from .branched_surface import smooth, unit


def connect(assembly, main, branch_grids):
    main = np.array(main, copy=True)
    branches = []
    for prepared, source in zip(assembly.branches, branch_grids):
        grid = np.array(source, copy=True)
        side = prepared.connection.boundary
        oriented = main if side == -1 else main[::-1]
        _connect_strip(oriented, grid, prepared, assembly.flip != (side == 0))
        grid[:, 0] = main[side, prepared.seam]
        branches.append(grid)
    return main, tuple(branches)


def _rails(main, branch, prepared):
    width = prepared.connection.width
    distances = np.mean(np.linalg.norm(np.diff(main[:, prepared.seam], axis=0), axis=-1), axis=1)
    coordinates = np.r_[0., np.cumsum(distances)]
    coordinates /= max(coordinates[-1], 1e-12)
    i = max(1, min(len(main)-2, int(np.searchsorted(coordinates, 1-width))))
    k = max(1, min(branch.shape[1]-2, int(np.searchsorted(prepared.along, width))))
    return i, k


def _strip_geometry(main, branch, seam, i, k):
    first, last = main[i, seam], branch[:, k]
    strip = np.concatenate((main[i:, seam].transpose(1, 0, 2), branch[:, 1:k+1]), axis=1)
    spans = np.cumsum(np.linalg.norm(np.diff(strip, axis=1), axis=2), axis=1)
    spans = np.column_stack((np.zeros(len(spans)), spans))
    lengths = spans[:, -1:]
    t = spans / np.maximum(lengths, 1e-12)
    incoming = unit(first-main[i-1, seam]) * lengths
    outgoing = unit(branch[:, k+1]-last) * lengths
    return first, last, incoming, outgoing, t, strip


def hermite(first, last, incoming, outgoing, t):
    v = t[..., None]
    return ((2*v**3-3*v**2+1)*first[:, None] + (v**3-2*v**2+v)*incoming[:, None]
            + (-2*v**3+3*v**2)*last[:, None] + (v**3-v**2)*outgoing[:, None])


def _fullness_normal(main, branch, seam, i, k, flip):
    along = np.gradient(main[i, seam], axis=0)
    first = unit(np.cross(main[i, seam]-main[i-1, seam], along))
    second = unit(np.cross(branch[:, k+1]-branch[:, k], np.gradient(branch[:, k], axis=0)))
    combined = first + second
    normal = np.where(np.linalg.norm(combined, axis=1)[:, None] > 1e-10, unit(combined), first)
    return -normal if flip else normal


def _connect_strip(main, branch, prepared, flip):
    seam = prepared.seam
    i, k = _rails(main, branch, prepared)
    first, last, incoming, outgoing, t, old = _strip_geometry(main, branch, seam, i, k)
    target = hermite(first, last, incoming, outgoing, t)
    normal = _fullness_normal(main, branch, seam, i, k, flip)
    target += normal[:, None] * (16*t*t*(1-t)**2)[..., None] * prepared.connection.fullness
    weight = smooth(np.minimum(prepared.across, 1-prepared.across)/.1)[:, None, None]
    result = old*(1-weight) + target*weight
    count = len(main)-i
    main[i:, seam] = result[:, :count].transpose(1, 0, 2)
    branch[:, :k+1] = result[:, count-1:]
