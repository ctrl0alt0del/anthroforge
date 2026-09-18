"""Compile through the ordinary Fiber Surface and Muscle numeric evaluators."""
import numpy as np
from ..vcp.fiber_surface import FiberSurfaceSpec, evaluate_fiber_surface, prepare_loft_rows
from ..vcp.muscle_numeric import MuscleNumericSpec, make_muscle_request, execute_muscle_batch
from .errors import require


def loft(rows, values, closed):
    spec = FiberSurfaceSpec(closed_along_fibers=closed, target_node_count=len(rows[0]))
    surface = evaluate_fiber_surface(rows, spec)
    grid = np.asarray(surface.rows)
    sources = np.asarray(prepare_loft_rows(rows, len(rows[0]), closed, False))
    distances = np.sum((grid[:, None] - sources[None, :]) ** 2, axis=(2, 3))
    indices = np.argmin(distances, axis=0)
    u = np.interp(np.arange(len(grid)), indices, values)
    return grid, u


def boundary_band(config, shape):
    if 'native_boundary_band' in config:
        return float(config['native_boundary_band'])
    rows, columns = shape[:2]
    boundary = config['boundary']
    widths = [boundary['across'] * (rows - 1), boundary['along'] * (columns - 1)]
    return float(np.clip(np.mean(widths), .1, 16.))


def properties(config, shape):
    require(config['mode'] in ('section_profile', 'control_point', 'distributed'), 'PROFILE_MODE_UNSUPPORTED')
    if config['mode'] == 'section_profile':
        return section_properties(config)
    return dict(inflation_enabled=config['enabled'], inflation_mode='CTRL_POINT' if config['mode'] == 'control_point' else 'DISTRIBUTED',
        inflation_max_value=config['amount'], inflation_falloff_type=config.get('falloff', 'gaussian').upper(),
        inflation_falloff_radius=config.get('radius', .2), inflation_direction_depth=config.get('direction_depth', .05),
        inflation_boundary_strength=config['boundary']['strength'], inflation_boundary_band=boundary_band(config, shape),
        inflation_boundary_power=config['boundary']['power'], inflation_length_taper_band=float(np.clip(config.get('length_taper', .2), .01, .49)),
        flip_normals=config['flip_normals'])


def evaluate(grid, u, s, config, closed):
    from .inflation import sample
    point = (0, 0, 0) if config["mode"] == "section_profile" else config.get('control_world')
    if point is None:
        point = sample(grid, u, s, *config.get('control', [.5, .5]), closed)
    values = properties(config, grid.shape)
    spec = MuscleNumericSpec(target_count=len(grid[0]), densify=False, closed_u=closed,
        close_across_fibers=False, topology_flip_normals=False, closed_v=False, control_world=tuple(point), **numeric_properties(values))
    result = execute_muscle_batch([make_muscle_request('authoring', grid, spec)]).results[0]
    require(not result.error, 'NATIVE_GEOMETRY_FAILED', result.error)
    return result, values, list(point)


def build(rows, values, config, closed):
    grid, u = loft(rows, values, closed)
    s = np.linspace(0., 1., len(grid[0]), endpoint=not closed)
    result, native, point = evaluate(grid, u, s, config, closed)
    return dict(base=result.base_vertices.tolist(), inflated=result.inflated_vertices.tolist(), faces=result.faces.tolist(),
                u=u.tolist(), s=s.tolist(), native_properties=native, native_control_world=point)


def rebuild(output, config):
    fibers = output['fibers']
    if all('points' in fiber for fiber in fibers):
        return build([f['points'] for f in fibers], [f['u'] for f in fibers], config, fibers[0]['closed'])
    grid = np.asarray(output['base']).reshape(len(output['u']), len(output['s']), 3)
    result, native, point = evaluate(grid, output['u'], output['s'], config, fibers[0]['closed'])
    return dict(inflated=result.inflated_vertices.tolist(), native_properties=native, native_control_world=point)


def section_properties(config):
    from ..vcp.muscle_section_profile import SectionProfileSpec, profile_properties
    spec = SectionProfileSpec(config['profile_version'], tuple(config['depths']), tuple(config['peaks']),
                              config['roundness'], config['direction'].upper())
    return dict(profile_properties(spec), inflation_enabled=config['enabled'], flip_normals=config['flip_normals'], inflation_mode='SECTION_PROFILE')


def numeric_properties(values):
    from ..vcp.muscle_section_profile import PROFILE_FIELDS, SectionProfileSpec
    if values['inflation_mode'] != 'SECTION_PROFILE':
        return values
    numeric = dict(inflation_max_value=0., inflation_falloff_type='GAUSSIAN', inflation_falloff_radius=.2,
        inflation_direction_depth=.05, inflation_boundary_strength=.7, inflation_boundary_band=2.,
        inflation_boundary_power=1.5, inflation_length_taper_band=.2)
    numeric.update({key: value for key, value in values.items() if key not in PROFILE_FIELDS})
    numeric['section_profile'] = SectionProfileSpec(*(values[key] for key in PROFILE_FIELDS))
    return numeric
