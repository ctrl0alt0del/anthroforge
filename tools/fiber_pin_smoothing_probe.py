"""Tune arc-length-aware pin smoothing from a recorded real Fiber."""

import argparse
import json

import numpy as np


def _args():
    parser = argparse.ArgumentParser(); parser.add_argument("record")
    return parser.parse_args()


def _turns(points):
    edges = np.diff(points, axis=0); unit = edges / np.maximum(np.linalg.norm(edges, axis=1)[:, None], 1.0e-12)
    return np.degrees(np.arccos(np.clip(np.sum(unit[:-1] * unit[1:], axis=1), -1.0, 1.0)))


def _metrics(points):
    values = _turns(points)
    return float(np.max(values)), float(np.percentile(values, 95.0)), float(np.sum(values))


def _arc_parameter(points):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1); values = np.concatenate(([0.0], np.cumsum(lengths)))
    return values / max(float(values[-1]), 1.0e-12), float(values[-1])


def _direction(value):
    length = float(np.linalg.norm(value))
    return value / length if length > 1.0e-12 else np.zeros(3)


def _pin_tangent(points, left, pin, right):
    before = _direction(points[pin] - points[left]); after = _direction(points[right] - points[pin])
    value = before + after
    return _direction(value) if np.linalg.norm(value) > 1.0e-12 else _direction(points[right] - points[left])


def _hermite(p0, p1, m0, m1, value):
    t = value[:, None]; t2, t3 = t * t, t * t * t
    return (2*t3-3*t2+1)*p0 + (t3-2*t2+t)*m0 + (-2*t3+3*t2)*p1 + (t3-t2)*m1


def _side(points, start, end, tangent_start, tangent_end):
    values = points[start:end + 1]; parameter, length = _arc_parameter(values)
    return _hermite(values[0], values[-1], length*tangent_start, length*tangent_end, parameter)


def _window(points, pin, left, right):
    tangent = _pin_tangent(points, left, pin, right); output = points.copy()
    output[left:pin + 1] = _side(points, left, pin, _direction(points[left + 1] - points[left]), tangent)
    output[pin:right + 1] = _side(points, pin, right, tangent, _direction(points[right] - points[right - 1]))
    return output


def _end_window(points, start, end, first):
    output = points.copy(); chord = _direction(points[end] - points[start])
    left = chord if first else _direction(points[start + 1] - points[start])
    right = _direction(points[end] - points[end - 1]) if first else chord
    output[start:end + 1] = _side(points, start, end, left, right)
    return output


def _ranges(pins, radius):
    rows = [(pins[0], pins[0], min(pins[1], pins[0]+radius), True)]
    rows += [(max(pins[i-1], pin-radius), pin, min(pins[i+1], pin+radius), None) for i, pin in enumerate(pins[1:-1], 1)]
    return rows + [(max(pins[-2], pins[-1]-radius), pins[-1], pins[-1], False)]


def _smooth(points, pins, radius, strength):
    source = points.copy(); delta = np.zeros_like(points); counts = np.zeros(len(points))
    for left, pin, right, first in _ranges(pins, radius):
        candidate = _window(source, pin, left, right) if first is None else _end_window(source, left, right, first)
        delta[left:right+1] += candidate[left:right+1]-source[left:right+1]; counts[left:right+1] += 1
    moving = counts > 0; output = source.copy(); output[moving] += strength*delta[moving]/counts[moving, None]; output[pins] = source[pins]
    return output


def main():
    record = json.load(open(_args().record, encoding="utf-8")); points = np.asarray(record["v24"]["points"])
    pins = np.asarray((0, *[span["first_edge"] + span["edge_count"] for span in record["spans"][:-1]], len(points)-1))
    print("baseline", _metrics(points), "pins", pins.tolist())
    for radius in (2, 3, 4, 5, 6):
        for strength in (.25, .5, .75, 1.0):
            output = _smooth(points, pins, radius, strength)
            print(radius, strength, _metrics(output), float(np.max(np.linalg.norm(output-points, axis=1))))


if __name__ == "__main__":
    main()
