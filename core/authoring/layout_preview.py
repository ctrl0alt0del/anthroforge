"""Coordinate-view overlay for reviewing planned controls without scene edits."""
from html import escape
import numpy as np
from .preview import svg as region_svg


def svg(polygons, plan):
    points = np.concatenate(polygons)
    low = points.min(axis=0)
    scale = 250/max(float(np.ptp(points, axis=0).max()), 1e-9)
    title = f"Fiber plan: {plan['fiber_count']} fibers, {plan['middle_point_count']} middle points"
    overlays = [panel(plan, axes, low, scale, i) for i, axes in enumerate(((0, 1), (0, 2), (1, 2)))]
    stage = 'Native fibers solved; muscle not validated.' if plan['native_solver_validated'] else 'Guide paths; native solve pending.'
    label = f"Blue: endpoints; orange: middle points. Sampled error {plan['max_sampled_error']:.5g} / {plan['tolerance']:.5g}. "+stage
    footer = '<text x="15" y="340" fill="white" font-size="12">'+escape(label)+'</text>'
    return region_svg(polygons, title).replace('</svg>', ''.join(overlays)+footer+'</svg>')


def panel(plan, axes, low, scale, index):
    shapes = [f'<text x="{index*320+25}" y="48" fill="white">'+('XY', 'XZ', 'YZ')[index]+'</text>']
    for fiber in plan['fibers']:
        values = (np.asarray(fiber.get('solved_path', fiber['reference_path']))-low)*scale
        xy = np.column_stack((index*320+25+values[:, axes[0]], 315-values[:, axes[1]]))
        coords = ' '.join(f'{x:.3f},{y:.3f}' for x, y in xy)
        shapes.append(f'<polyline points="{coords}" fill="none" stroke="#ffb454" stroke-width="2"/>')
        controls = (np.array([p['anchor']['point'] for p in fiber['points']])-low)*scale
        controls = np.column_stack((index*320+25+controls[:, axes[0]], 315-controls[:, axes[1]]))
        shapes.extend(marker(point, i in (0, len(controls)-1)) for i, point in enumerate(controls))
    return ''.join(shapes)


def marker(point, endpoint):
    color = '#65caff' if endpoint else '#ffb454'
    return f'<circle cx="{point[0]:.3f}" cy="{point[1]:.3f}" r="3.5" fill="{color}" stroke="#182128" stroke-width="1"/>'
