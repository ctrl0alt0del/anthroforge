"""Arc-length-aware local geometry for smoothing hard Fiber pins."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PinWindow:
    left: int
    pin: int
    right: int
    anchor: int
    endpoint: int = 0


def smoothing_windows(points, pins, radius=4, threshold=12.0):
    values, indices = _points(points), _pins(pins, len(points)); rows = _windows(indices, int(radius))
    return tuple(row for row in rows if _window_peak(values, row) >= float(threshold))


def smoothing_candidate(points, pins, windows, strength=1.0):
    source = _points(points); delta = np.zeros_like(source); counts = np.zeros(len(source))
    for window in tuple(windows):
        _accumulate(source, delta, counts, window)
    moving = counts > 0; output = source.copy()
    output[moving] += float(strength) * delta[moving] / counts[moving, None]
    output[_pins(pins, len(source))] = source[_pins(pins, len(source))]
    return output


def surface_tangent_candidate(points, window, normal, side, strength=1.5):
    source = _points(points); tangent = _surface_tangent(source, window, normal, side)
    target = _tangent_window(source, window, tangent)
    output = source + float(strength) * (target - source)
    output[window.pin] = source[window.pin]; return output


def pin_interpolating_candidate(points, pins, strength=1.5):
    source = _points(points); indices = _pins(pins, len(source)); anchors = source[indices]
    tangents = _anchor_directions(anchors); output = source.copy()
    for span, (left, right) in enumerate(zip(indices[:-1], indices[1:])):
        parameter = np.linspace(0.0, 1.0, int(right-left+1)); length = _arc_parameter(source[left:right+1])[1]
        output[left:right+1] = _hermite(anchors[span], anchors[span+1], strength*length*tangents[span],
                                      strength*length*tangents[span+1], parameter)
    output[indices] = anchors; return output


def window_turn_peak(points, window):
    return _window_peak(_points(points), window)


def curvature_energy(points, reference=None):
    values = _points(points); rest = values if reference is None else _points(reference)
    turns = _turn_radians(values); lengths = np.linalg.norm(np.diff(rest, axis=0), axis=1)
    voronoi = 0.5 * (lengths[:-1] + lengths[1:]); curvature = 2.0 * np.tan(0.5 * turns)
    return float(np.sum(curvature * curvature / np.maximum(voronoi, 1.0e-12)))


def turn_metrics(points):
    turns = np.degrees(_turn_radians(_points(points)))
    return (_safe_stat(turns, np.max), _safe_stat(turns, lambda row: np.percentile(row, 95.0)),
            float(np.sum(turns)))


def _points(points):
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
        raise ValueError("points must be a finite (N, 3) array")
    return values


def _pins(pins, count):
    values = np.asarray(tuple(pins), dtype=np.int64)
    if len(values) < 2 or values[0] != 0 or values[-1] != count - 1 or np.any(np.diff(values) <= 0):
        raise ValueError("pins must be strictly ordered and include both endpoints")
    return values


def _windows(pins, radius):
    rows = [PinWindow(0, 0, min(int(pins[1]), radius), 0, 1)]
    rows += [_internal_window(pins, index, radius) for index in range(1, len(pins) - 1)]
    rows.append(PinWindow(max(int(pins[-2]), int(pins[-1]) - radius), int(pins[-1]), int(pins[-1]), len(pins) - 1, -1))
    return rows


def _internal_window(pins, index, radius):
    pin = int(pins[index]); left = max(int(pins[index - 1]), pin - radius)
    right = min(int(pins[index + 1]), pin + radius)
    return PinWindow(left, pin, right, index)


def _window_peak(points, window):
    turns = np.degrees(_turn_radians(points)); start = max(0, window.left - 1)
    stop = min(len(turns), window.right)
    return float(np.max(turns[start:stop])) if stop > start else 0.0


def _accumulate(source, delta, counts, window):
    target = _window_candidate(source, window); rows = slice(window.left, window.right + 1)
    delta[rows] += target[rows] - source[rows]
    counts[rows] += 1.0


def _window_candidate(points, window):
    if window.endpoint:
        return _endpoint_candidate(points, window)
    tangent = _pin_tangent(points, window.left, window.pin, window.right); output = points.copy()
    output[window.left:window.pin + 1] = _side(points, window.left, window.pin, _edge_direction(points, window.left), tangent)
    output[window.pin:window.right + 1] = _side(points, window.pin, window.right, tangent, _edge_direction(points, window.right - 1))
    return output


def _surface_tangent(points, window, normal, side):
    vector = points[window.pin] - points[window.left] if side == "incoming" else points[window.right] - points[window.pin]
    direction = np.asarray(normal, dtype=np.float64); vector -= float(np.dot(vector, direction)) * direction
    return _direction(vector)


def _tangent_window(points, window, tangent):
    output = points.copy()
    output[window.left:window.pin + 1] = _side(points, window.left, window.pin, _edge_direction(points, window.left), tangent)
    output[window.pin:window.right + 1] = _side(points, window.pin, window.right, tangent, _edge_direction(points, window.right - 1))
    return output


def _endpoint_candidate(points, window):
    output = points.copy(); chord = _direction(points[window.right] - points[window.left])
    left = chord if window.endpoint > 0 else _edge_direction(points, window.left)
    right = _edge_direction(points, window.right - 1) if window.endpoint > 0 else chord
    output[window.left:window.right + 1] = _side(points, window.left, window.right, left, right)
    return output


def _pin_tangent(points, left, pin, right):
    incoming = _direction(points[pin] - points[left]); outgoing = _direction(points[right] - points[pin])
    combined = incoming + outgoing
    return _direction(combined) if np.linalg.norm(combined) > 1.0e-12 else _direction(points[right] - points[left])


def _edge_direction(points, edge):
    return _direction(points[int(edge) + 1] - points[int(edge)])


def _direction(value):
    length = float(np.linalg.norm(value))
    return np.asarray(value) / length if length > 1.0e-12 else np.zeros(3)


def _anchor_directions(points):
    edges = np.diff(points, axis=0); unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    rows = np.vstack((unit[0], unit[:-1] + unit[1:], unit[-1]))
    return rows / np.maximum(np.linalg.norm(rows, axis=1)[:, None], 1.0e-12)


def _side(points, start, end, first, last):
    rows = points[start:end + 1]; parameter, length = _arc_parameter(rows)
    return _hermite(rows[0], rows[-1], length * first, length * last, parameter)


def _arc_parameter(points):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    values = np.concatenate(([0.0], np.cumsum(lengths))); total = max(float(values[-1]), 1.0e-12)
    return values / total, total


def _hermite(first, last, tangent_first, tangent_last, parameter):
    value = parameter[:, None]; square, cube = value * value, value * value * value
    return ((2*cube-3*square+1)*first + (cube-2*square+value)*tangent_first +
            (-2*cube+3*square)*last + (cube-square)*tangent_last)


def _turn_radians(points):
    edges = np.diff(points, axis=0)
    unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    return np.arccos(np.clip(np.sum(unit[:-1] * unit[1:], axis=1), -0.999999999, 0.999999999))


def _safe_stat(values, function):
    return float(function(values)) if len(values) else 0.0
