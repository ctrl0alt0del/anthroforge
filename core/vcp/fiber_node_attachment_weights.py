"""Bind-time C2 owner transitions along hard-pin-partitioned reference arcs.

This is a one-dimensional local blending rule, not a biharmonic shape solver.
The reference geometry is never smoothed and weights never change during propagation.
"""
from itertools import groupby

import numpy as np


def attachment_owner_weights(points, owners, pins, cyclic=False):
    count = len(owners); pins = sorted(set(int(index) for index in pins))
    if len(points) != count or count < 2 or not pins: raise ValueError('Invalid attachment reference')
    if any(index < 0 or index >= count for index in pins): raise ValueError('Invalid hard pin index')
    if not cyclic and (pins[0] != 0 or pins[-1] != count - 1): raise ValueError('Open endpoints must be pinned')
    result = [((owner, 1.0),) for owner in owners]
    ends = pins[1:] + ([pins[0] + count] if cyclic else [])
    for start, end in zip(pins, ends): _span_weights(points, owners, start, end, result)
    for index in pins: result[index] = ((owners[index], 1.0),)
    return tuple(result)


def _span_weights(points, owners, start, end, result):
    indices = tuple(index % len(owners) for index in range(start, end + 1))
    values = np.asarray([points[index] for index in indices], dtype=np.float64)
    distances = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(values, axis=0), axis=1))))
    controls = _controls(distances, [owners[index] for index in indices]); cursor = 0
    for local, index in enumerate(indices[1:-1], 1):
        while cursor + 2 < len(controls) and distances[local] >= controls[cursor + 1][0]: cursor += 1
        result[index] = _between(distances[local], controls[cursor], controls[cursor + 1])


def _controls(distances, owners):
    controls = [(0.0, owners[0])]
    runs = [(owner, [row[0] for row in rows]) for owner, rows in groupby(enumerate(owners), key=lambda row: row[1])]
    for first, last in zip(runs, runs[1:]):
        for position, owner in _transition_controls(distances, first, last):
            if position > controls[-1][0]: controls.append((float(position), owner))
    if distances[-1] > controls[-1][0]: controls.append((float(distances[-1]), owners[-1]))
    return controls if len(controls) > 1 else controls * 2


def _transition_controls(distances, first, last):
    left, right = first[1], last[1]; gap = distances[right[0]] - distances[left[-1]]
    center = (distances[left[-1]] + distances[right[0]]) * .5
    extent = .5 * min(max(distances[left[-1]] - distances[left[0]], gap),
                       max(distances[right[-1]] - distances[right[0]], gap))
    return ((max(distances[left[0]], center - extent), first[0]),
            (min(distances[right[-1]], center + extent), last[0]))


def _between(position, first, last):
    if first[1] == last[1]: return ((first[1], 1.0),)
    fraction = np.clip((position - first[0]) / max(last[0] - first[0], 1e-30), 0.0, 1.0)
    weight = float(fraction ** 3 * (10.0 + fraction * (-15.0 + 6.0 * fraction)))
    if weight <= 1e-12: return ((first[1], 1.0),)
    if weight >= 1.0 - 1e-12: return ((last[1], 1.0),)
    return ((first[1], 1.0 - weight), (last[1], weight))
