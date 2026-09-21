"""Explicit curve sampling; entering an editor never calls these operations."""
from uuid import uuid4
import numpy as np
from . import free_path


def allocation(lengths, intervals):
    lengths = np.asarray(lengths, dtype=float)
    if intervals < len(lengths): raise ValueError('Sampling resolution cannot preserve every knot and structural endpoint.')
    residual = intervals - len(lengths); weights = lengths / max(float(lengths.sum()), 1e-30)
    ideal = residual * weights; counts = np.floor(ideal).astype(int) + 1
    order = np.argsort(-(ideal - np.floor(ideal)), kind='stable')
    counts[order[:intervals - int(counts.sum())]] += 1
    return counts


def bezier(knots, resolution, cyclic=False):
    from mathutils import Vector
    from mathutils.geometry import interpolate_bezier
    pairs = list(zip(knots, knots[1:] + knots[:1])) if cyclic else list(zip(knots, knots[1:]))
    lengths = [sum(np.linalg.norm(np.asarray(b) - a) for a, b in zip(_controls(a, b), _controls(a, b)[1:])) for a, b in pairs]
    counts = allocation(lengths, int(resolution) - (0 if cyclic else 1)); output = []
    for (first, last), count in zip(pairs, counts):
        points = interpolate_bezier(*(Vector(p) for p in _controls(first, last)), int(count) + 1)
        output.extend(dict(sample_id=first['sample_id'] if i == 0 else str(uuid4()), co=list(p)) for i, p in enumerate(points[:-1]))
    if not cyclic: output.append(dict(sample_id=knots[-1]['sample_id'], co=list(knots[-1]['co'])))
    free_path.coordinates([row['co'] for row in output], 'LOOP' if cyclic else 'OPEN')
    return output


def _controls(first, last):
    return [first['co'], first['handle_right'], last['handle_left'], last['co']]


def input_payload(value, topology):
    if value['space'] not in ('WORLD', 'ROOT_LOCAL'): raise ValueError('Invalid path coordinate space.')
    if value['representation'] == 'POLY': samples = value['samples']
    elif value['representation'] == 'BEZIER': samples = bezier(value['knots'], value['resolution'], topology == 'LOOP')
    else: raise ValueError('Unsupported path representation.')
    return free_path.validate(dict(version=1, space='ROOT_LOCAL', topology=topology, samples=samples,
                                   structural=value['structural'], capture_revision=0))


def resample_spans(points, indices, count, cyclic=False):
    source = np.asarray(points); spans = list(free_path.spans(source, indices, cyclic))
    lengths = [np.linalg.norm(np.diff(source[span], axis=0), axis=1).sum() for span in spans]
    counts = allocation(lengths, count - (0 if cyclic else 1)); rows, roots = [], []
    for span, intervals in zip(spans, counts):
        roots.append(len(rows)); rows.extend(free_path.sample_poly(source[span], intervals + 1)[:-1])
    if not cyclic: roots.append(len(rows)); rows.append(source[indices[-1]])
    return np.asarray(rows), roots
