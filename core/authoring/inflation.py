"""Vectorized inflation in a persistent material chart."""
import numpy as np
from .geometry import normalized
from .distributed import limit


def loft(rows, coordinates, minimum=17):
    coordinates = np.asarray(coordinates)
    u = np.unique(np.r_[np.linspace(0., 1., minimum), coordinates])
    values = np.asarray(rows)
    grid = np.empty((len(u), values.shape[1], 3))
    for column in range(values.shape[1]):
        for axis in range(3):
            grid[:, column, axis] = np.interp(u, coordinates, values[:, column, axis])
    return grid, u


def material_loft(rows, row_s, u, s, closed):
    prepared = []
    for row, coordinates in zip(rows, row_s):
        source = np.vstack((row, row[0])) if closed else np.asarray(row)
        values = np.r_[coordinates, 1.] if closed else coordinates
        prepared.append(np.column_stack([np.interp(s, values, source[:, axis]) for axis in range(3)]))
    return loft(prepared, u)


def normals(grid, closed=False):
    across = np.gradient(grid, axis=0)
    along = np.roll(grid, -1, axis=1) - np.roll(grid, 1, axis=1) if closed else np.gradient(grid, axis=1)
    return normalize_grid(np.cross(across, along))


def normalize_grid(values):
    sizes = np.linalg.norm(values, axis=2)
    good = np.argwhere(sizes > 1e-14)
    if not len(good):
        return normalized(values)
    result = values.copy()
    for index in np.argwhere(sizes <= 1e-14):
        source = good[np.argmin(np.sum((good-index)**2, axis=1))]
        result[tuple(index)] = values[tuple(source)]
    return normalized(result)


def sample(grid, u_values, s_values, u, s, closed=False):
    columns = np.asarray(s_values)
    values = np.concatenate((grid, grid[:, :1]), axis=1) if closed else grid
    columns = np.r_[columns, 1.] if closed else columns
    across = np.array([[np.interp(s, columns, row[:, axis]) for axis in range(3)] for row in values])
    return np.array([np.interp(u, u_values, across[:, axis]) for axis in range(3)])


def smooth(value):
    t = np.clip(value, 0., 1.)
    return t * t * (3 - 2 * t)


def boundary(u, s, spec, closed):
    du, ds = np.minimum(u, 1-u)[:, None], np.minimum(s, 1-s)[None, :]
    across = du / spec["across"] if spec["across"] else np.full_like(du, np.inf)
    along = ds / spec["along"] if spec["along"] and not closed else np.full_like(ds, np.inf)
    weight = (1-spec["strength"]) + spec["strength"] * smooth(np.minimum(across, along)) ** spec["power"]
    weight = np.broadcast_to(weight, (len(u), len(s))).copy()
    weight[(du[:, 0] < 1e-12), :] = 0
    if not closed:
        weight[:, ds[0] < 1e-12] = 0
    return weight


def inflate(grid, u, s, config, closed=False):
    from .errors import require
    require(config['mode'] in ('section_profile', 'control_point', 'distributed'), 'PROFILE_MODE_UNSUPPORTED')
    if config['mode'] == 'section_profile':
        return _section_profile(grid, config, closed)
    if not config["enabled"]:
        return np.array(grid, copy=True)
    normal = normals(grid, closed)
    edge = boundary(np.asarray(u), np.asarray(s), config["boundary"], closed)
    sign = -1. if config["flip_normals"] else 1.
    if config["mode"] == "distributed":
        weight = smooth(np.minimum(s, 1-np.asarray(s)) / config["length_taper"]) if config["length_taper"] else np.ones(len(s))
        amount = limit(grid, normal, config["amount"] * edge * weight, closed)
        return grid + normal * (amount * sign)[..., None]
    return _control(grid, u, s, config, closed, normal, edge, sign)


def _control(grid, u, s, config, closed, normal, edge, sign):
    control = np.asarray(config["control_world"] if "control_world" in config else sample(grid,u,s,*config["control"],closed))
    index = np.unravel_index(np.argmin(np.linalg.norm(grid-control, axis=2)), grid.shape[:2])
    source = control - normal[index] * config["direction_depth"] * sign
    delta = grid - source
    size = np.linalg.norm(delta, axis=2, keepdims=True)
    direction = np.divide(delta, size, out=np.broadcast_to(normal[index], delta.shape).copy(), where=size > 1e-12)
    t = np.linalg.norm(grid-control, axis=2) / config["radius"]
    weights = {"gaussian": lambda: np.exp(-4*t*t), "linear": lambda: np.maximum(0, 1-t), "smoothstep": lambda: 1-smooth(t)}
    return grid + direction * (config["amount"] * edge * weights[config["falloff"]]())[..., None]


def faces(rows, columns, closed=False):
    return np.array([(i*columns+j, (i+1)*columns+j, (i+1)*columns+(j+1)%columns, i*columns+(j+1)%columns)
                     for i in range(rows-1) for j in range(columns if closed else columns-1)], dtype=int)


def resolved_preset(preset, resolver, references):
    config = dict(preset)
    if config["mode"] == "section_profile":
        config["depths"] = [resolver.measure(row, references) for row in config["depths"]]
    for key in ("amount", "radius", "direction_depth"):
        if key in config:
            config[key] = resolver.measure(config[key], references)
    return config


def _section_profile(grid, config, closed):
    from .errors import require
    from ..vcp.muscle_section_profile import SectionProfileSpec, apply_profile
    require(not closed, 'PROFILE_DOMAIN_UNSUPPORTED')
    spec = SectionProfileSpec(config['profile_version'], tuple(config['depths']), tuple(config['peaks']),
                              config['roundness'], config['direction'].upper())
    return apply_profile(grid, spec, config['enabled'], config['flip_normals'])
