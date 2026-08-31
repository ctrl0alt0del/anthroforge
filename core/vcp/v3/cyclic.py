"""Globally coupled cyclic representation for Fiber V3."""

from dataclasses import replace

import numpy as np

from ..v2.contact_core import _span_counts
from ..v2.contracts import V2AnchorRole, V2Topology


def is_cyclic_request(request):
    return request.settings.topology is V2Topology.CYCLIC


def v3_reference(request):
    if not is_cyclic_request(request):
        from ..v2.contact_core import _direct_reference
        return _direct_reference(request)
    return _cyclic_reference(request)


def _cyclic_reference(request):
    anchors = np.asarray([row.point for row in request.anchors], dtype=np.float64)
    closed = np.vstack((anchors, anchors[0]))
    counts = _span_counts(closed, request.settings.node_count)
    return _cyclic_rows(closed, counts)


def _cyclic_rows(anchors, counts):
    rows, pins = [anchors[0]], [0]
    for span, (start, end) in enumerate(zip(anchors[:-1], anchors[1:])):
        limit = counts[span] + int(span + 2 < len(anchors))
        rows.extend(start + (end - start) * (step / counts[span]) for step in range(1, limit))
        if span + 2 < len(anchors): pins.append(len(rows) - 1)
    return np.ascontiguousarray(rows), tuple(pins)


def linearized_cyclic_request(request, seed):
    anchors = _linear_anchors(request.anchors)
    settings = replace(request.settings, topology=V2Topology.OPEN,
                       node_count=request.settings.node_count + 1)
    warm = np.vstack((np.asarray(seed, dtype=np.float64), seed[0]))
    return replace(request, settings=settings, anchors=anchors,
                   warm_seed=tuple(map(tuple, warm)), source_revision=request.source_revision + ":cyclic")


def _linear_anchors(anchors):
    rows = [replace(anchors[0], role=V2AnchorRole.ENDPOINT_A)]
    rows.extend(replace(row, role=V2AnchorRole.TOUCH) for row in anchors[1:])
    last = replace(anchors[0], role=V2AnchorRole.ENDPOINT_B,
                   authored_index=max(row.authored_index for row in anchors) + 1)
    return tuple(rows + [last])


def close_seed(seed):
    values = np.asarray(seed, dtype=np.float64)
    return np.vstack((values, values[0]))


def cyclic_planner_seed(planner, pins, count):
    from ..v2.contact_core import _resample
    source = close_seed(planner.reference); old = tuple(planner.pin_indices) + (count,)
    targets = tuple(pins) + (count,); rows = []
    for prior, target in zip(zip(old[:-1], old[1:]), zip(targets[:-1], targets[1:])):
        part = _resample(source[prior[0]:prior[1] + 1], target[1] - target[0] + 1)
        rows.extend(part if not rows else part[1:])
    return np.ascontiguousarray(rows[:-1])


def open_result(points):
    values = tuple(points or ())
    return values[:-1] if len(values) > 1 else values


def cyclic_lengths(points):
    values = np.asarray(points, dtype=np.float64)
    if len(values) < 2: return np.empty(0, dtype=np.float64)
    return np.linalg.norm(np.roll(values, -1, axis=0) - values, axis=1)
