"""Plain-array cubic span basis for the High-Order Fiber experiment."""

from dataclasses import dataclass
from math import ceil

import numpy as np
from scipy.interpolate import BSpline


@dataclass(frozen=True)
class HighOrderBasis:
    output: np.ndarray
    proxy: np.ndarray
    controls: np.ndarray
    pin_controls: tuple
    proxy_pins: tuple
    spans: tuple


def build_high_order_basis(seed, pins, stride=2, proxy_subdivisions=4):
    points = np.asarray(seed, dtype=np.float64); indices = tuple(map(int, pins))
    specs = _span_specs(points, indices, stride, proxy_subdivisions)
    output, proxy, controls, pin_controls, proxy_pins = _join_specs(specs, len(points))
    spans = tuple((row[0], row[1], row[2].shape[1]) for row in specs)
    return HighOrderBasis(output, proxy, controls, pin_controls, proxy_pins, spans)


def structural_system(basis, reference, settings, pins):
    output = basis.output; count = len(reference)
    d1, d2 = _difference_matrices(count, pins)
    h = 1.0 / max(1, count - 1)
    length = settings.length_weight / h
    bend = settings.curvature_weight / h ** 3
    matrix = settings.fidelity_weight * (output.T @ output)
    matrix += length * (d1 @ output).T @ (d1 @ output)
    matrix += bend * (d2 @ output).T @ (d2 @ output)
    rhs = settings.fidelity_weight * output.T @ np.asarray(reference)
    return matrix, rhs


def structural_energy(controls, basis, reference, settings, pins):
    points = basis.output @ controls; d1, d2 = _difference_matrices(len(points), pins)
    h = 1.0 / max(1, len(points) - 1)
    fidelity = settings.fidelity_weight * np.sum((points - reference) ** 2)
    length = settings.length_weight / h * np.sum((d1 @ points) ** 2)
    bend = settings.curvature_weight / h ** 3 * np.sum((d2 @ points) ** 2)
    return float(fidelity + length + bend)


def _span_specs(points, pins, stride, proxy_subdivisions):
    specs = []
    for first, last in zip(pins[:-1], pins[1:]):
        count = max(4, int(ceil((last - first) / max(1.0, float(stride)))) + 1)
        output = _basis(count, np.linspace(0.0, 1.0, last - first + 1))
        samples = proxy_subdivisions * (last - first) + 1
        proxy = _basis(count, np.linspace(0.0, 1.0, samples))
        controls = _fit_controls(output, points[first:last + 1])
        specs.append((first, last, output, proxy, controls))
    return tuple(specs)


def _basis(count, parameters):
    degree = min(3, count - 1); internal = count - degree - 1
    middle = np.linspace(0.0, 1.0, internal + 2)[1:-1]
    knots = np.r_[np.zeros(degree + 1), middle, np.ones(degree + 1)]
    return np.asarray(BSpline(knots, np.eye(count), degree)(parameters))


def _fit_controls(basis, points):
    controls = np.empty((basis.shape[1], 3)); controls[0], controls[-1] = points[0], points[-1]
    residual = points - basis[:, [0, -1]] @ controls[[0, -1]]
    controls[1:-1] = np.linalg.lstsq(basis[:, 1:-1], residual, rcond=1.0e-10)[0]
    return controls


def _join_specs(specs, count):
    control_count = sum(row[2].shape[1] - 1 for row in specs) + 1
    output = np.zeros((count, control_count)); proxy_rows = []; controls = []
    pin_controls, proxy_pins, offset, proxy_offset = [0], [0], 0, 0
    for index, row in enumerate(specs):
        offset, proxy_offset = _append_spec(row, index, output, proxy_rows, controls,
                                            pin_controls, proxy_pins, offset, proxy_offset)
    return output, np.vstack(proxy_rows), np.vstack(controls), tuple(pin_controls), tuple(proxy_pins)


def _append_spec(row, index, output, proxy_rows, controls, control_pins, proxy_pins, offset, proxy_offset):
    first, last, local_out, local_proxy, local_controls = row
    columns = np.arange(local_out.shape[1]) + offset
    output[first:last + 1, columns] = local_out
    proxy_rows.append(_global_rows(local_proxy, columns, output.shape[1], bool(index)))
    controls.extend(local_controls if not index else local_controls[1:])
    offset += local_out.shape[1] - 1; proxy_offset += len(local_proxy) - 1
    control_pins.append(offset); proxy_pins.append(proxy_offset)
    return offset, proxy_offset


def _global_rows(local, columns, width, omit_first):
    rows = np.zeros((len(local), width)); rows[:, columns] = local
    return rows[1:] if omit_first else rows


def _difference_matrices(count, pins):
    first = np.zeros((count - 1, count))
    rows = np.arange(count - 1); first[rows, rows] = -1.0; first[rows, rows + 1] = 1.0
    centers = tuple(index for index in range(1, count - 1) if index not in set(pins[1:-1]))
    second = np.zeros((len(centers), count))
    for row, center in enumerate(centers): second[row, center - 1:center + 2] = (1.0, -2.0, 1.0)
    return first, second
