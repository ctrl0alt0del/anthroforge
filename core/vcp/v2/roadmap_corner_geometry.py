"""Local geometry for removing isolated ROADMAP corners."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RoadmapCornerWindow:
    left: int
    corner: int
    right: int
    turn: float


def roadmap_corner_window(points, pins, spans, radius=6, threshold=45.0):
    values = _points(points); turns = _turns(values)
    blocked = {int(value) for value in pins}
    for local in np.argsort(turns)[::-1]:
        node = int(local) + 1; span = _roadmap_span(spans, node)
        if node not in blocked and turns[local] >= threshold and span is not None:
            return _window(node, float(turns[local]), blocked, span, len(values), radius)
    return None


def roadmap_corner_candidate(points, window):
    source = _points(points); output = source.copy()
    rows = source[window.left:window.right + 1]; parameter, length = _arc_parameter(rows)
    first = length * _direction(source[window.left + 1] - source[window.left])
    last = length * _direction(source[window.right] - source[window.right - 1])
    output[window.left:window.right + 1] = _hermite(rows[0], rows[-1], first, last, parameter)
    return output


def _window(node, turn, pins, span, count, radius):
    low, high = int(span.first_edge), int(span.first_edge + span.edge_count)
    prior = max((value for value in pins if value < node), default=0)
    later = min((value for value in pins if value > node), default=count - 1)
    left = max(low, prior, node - int(radius)); right = min(high, later, node + int(radius))
    return RoadmapCornerWindow(left, node, right, turn) if left + 1 < node < right - 1 else None


def _roadmap_span(spans, node):
    for span in spans:
        branch = getattr(getattr(span, "branch", None), "value", "")
        if branch == "ROADMAP" and span.first_edge < node < span.first_edge + span.edge_count:
            return span
    return None


def _points(points):
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or values.shape[1:] != (3,) or not np.isfinite(values).all():
        raise ValueError("points must have finite shape (N, 3)")
    return values


def _turns(points):
    edges = np.diff(points, axis=0); lengths = np.linalg.norm(edges, axis=1)
    unit = edges / np.maximum(lengths[:, None], 1.0e-12)
    cosine = np.clip(np.sum(unit[:-1] * unit[1:], axis=1), -1.0, 1.0)
    return np.degrees(np.arccos(cosine))


def _arc_parameter(points):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    values = np.r_[0.0, np.cumsum(lengths)]; total = max(float(values[-1]), 1.0e-12)
    return values / total, total


def _direction(value):
    length = float(np.linalg.norm(value))
    return np.asarray(value) / length if length > 1.0e-12 else np.zeros(3)


def _hermite(first, last, tangent_first, tangent_last, parameter):
    value = parameter[:, None]; square, cube = value * value, value * value * value
    return ((2*cube-3*square+1)*first + (cube-2*square+value)*tangent_first +
            (-2*cube+3*square)*last + (cube-square)*tangent_last)
