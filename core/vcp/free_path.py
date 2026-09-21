"""Versioned, exact sampled paths. No Blender or solver dependencies."""
import hashlib
import json
from uuid import uuid4

import numpy as np

MAX_SAMPLES = 4096
FREE_FIELDS = ('behavior_mode', 'free_path_json', 'free_path_revision', 'free_sampling_resolution')


def is_free(fiber):
    return str(getattr(fiber, 'behavior_mode', 'CONTROLLED')) == 'FREE'


def fiber_geometry_point_count(fiber):
    if not is_free(fiber) and not retained_free_geometry(fiber): return int(getattr(fiber, 'node_count', 0))
    try: return len(decode(fiber.free_path_json)['samples'])
    except (ValueError, TypeError, KeyError): return 0


def retained_free_geometry(fiber):
    if not hasattr(fiber, 'get') or not fiber.get('af_controlled_retained_free', False): return False
    try:
        payload = decode(fiber.free_path_json)
        return payload.get('attachment_digest') == pair_digest(payload, fiber.node_attachments_json)
    except (ValueError, TypeError, KeyError): return False


def require_controlled(fiber):
    if is_free(fiber): raise ValueError('FREE_SOLVER_FORBIDDEN: Free paths never run a planner or solver.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def coordinates(points, topology='OPEN'):
    rows = np.asarray(points, dtype=float)
    minimum = 3 if topology == 'LOOP' else 2
    if topology not in {'OPEN', 'LOOP'}: raise ValueError('Invalid path topology.')
    if rows.ndim != 2 or rows.shape[1:] != (3,) or not minimum <= len(rows) <= MAX_SAMPLES:
        raise ValueError(f'Free path needs {minimum}..{MAX_SAMPLES} three-dimensional samples.')
    if not np.isfinite(rows).all(): raise ValueError('Non-finite path sample.')
    edges = np.diff(np.vstack((rows, rows[:1])) if topology == 'LOOP' else rows, axis=0)
    if np.any(np.linalg.norm(edges, axis=1) <= 1e-10): raise ValueError('Degenerate consecutive path samples.')
    return rows


def validate(value):
    if value.get('version') != 1 or value.get('space') != 'ROOT_LOCAL': raise ValueError('Unsupported Free path version/space.')
    samples, tags = value['samples'], value['structural']
    coordinates([row['co'] for row in samples], value['topology'])
    ids = [row['sample_id'] for row in samples]
    if any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError('Missing or duplicate sample identity.')
    validate_tags(tags, ids, value['topology'])
    return value


def validate_tags(tags, ids, topology):
    occurrences = [row['occurrence_id'] for row in tags]
    if not tags or any(not key for key in occurrences) or len(set(occurrences)) != len(occurrences):
        raise ValueError('Missing or duplicate structural occurrence.')
    if any(not row['point_id'] or row['sample_id'] not in ids for row in tags):
        raise ValueError('Structural sample or shared point is missing.')
    indices = [ids.index(row['sample_id']) for row in tags]
    if indices != sorted(set(indices)): raise ValueError('Structural sample order is invalid.')
    if topology == 'OPEN' and (indices[0] != 0 or indices[-1] != len(ids) - 1):
        raise ValueError('OPEN endpoints must be exact structural samples.')
    if topology == 'LOOP' and indices[0] != 0: raise ValueError('LOOP starts at its first structural occurrence.')


def decode(raw):
    try: return validate(json.loads(raw))
    except (KeyError, TypeError, json.JSONDecodeError) as error: raise ValueError('Invalid Free path payload.') from error


def encode(value):
    return json.dumps(validate(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def make(points, topology, anchors, indices, revision=0, sample_ids=None, occurrences=None):
    rows = coordinates(points, topology)
    keys = list(sample_ids) if sample_ids is not None else [str(uuid4()) for _ in rows]
    if len(keys) != len(rows) or len(anchors) != len(indices): raise ValueError('Path/tag count mismatch.')
    tags = [dict(occurrence_id=(occurrences[i] if occurrences else str(uuid4())),
                 point_id=point_id, sample_id=keys[index], role=role)
            for i, ((point_id, role), index) in enumerate(zip(anchors, indices))]
    return validate(dict(version=1, space='ROOT_LOCAL', topology=topology, capture_revision=revision,
                         samples=[dict(sample_id=key, co=list(row)) for key, row in zip(keys, rows)], structural=tags))


def tagged_indices(payload):
    mapping = {row['sample_id']: index for index, row in enumerate(payload['samples'])}
    return tuple(mapping[row['sample_id']] for row in payload['structural'])


def point_indices(payload, point_ids):
    tags, indices = payload['structural'], tagged_indices(payload)
    result = []
    for key in point_ids:
        found = [index for row, index in zip(tags, indices) if row['point_id'] == key]
        if len(found) != 1: raise ValueError('Missing or ambiguous structural junction: ' + key)
        result.append(found[0])
    return tuple(result)


def pair_digest(payload, attachments):
    return digest(dict(samples=[row['sample_id'] for row in payload['samples']], attachments=attachments))


def spans(points, indices, cyclic=False):
    rows = np.asarray(points, dtype=float)
    for first, last in zip(indices, (*indices[1:], indices[0] + len(rows)) if cyclic else indices[1:]):
        yield np.arange(first, last + 1) % len(rows)


def stations(points):
    lengths = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))))
    if lengths[-1] <= 1e-10: raise ValueError('Degenerate path span.')
    return lengths / lengths[-1]


def adjust_anchors(points, indices, targets, cyclic=False):
    rows = coordinates(points, 'LOOP' if cyclic else 'OPEN').copy()
    delta = {i: np.asarray(target, dtype=float) - rows[i] for i, target in zip(indices, targets)}
    source = rows.copy()
    for span in spans(rows, indices, cyclic):
        u = stations(source[span]); smooth = (3 * u ** 2 - 2 * u ** 3)[:, None]
        rows[span] = source[span] + (1 - smooth) * delta[span[0]] + smooth * delta[span[-1]]
    for index, target in zip(indices, targets): rows[index] = target
    return coordinates(rows, 'LOOP' if cyclic else 'OPEN')


def sample_poly(points, count):
    rows = np.asarray(points, dtype=float); u = stations(rows)
    if count < 2: raise ValueError('Insufficient samples for a structural span.')
    target = np.linspace(0, 1, count)
    return np.column_stack([np.interp(target, u, rows[:, axis]) for axis in range(3)])


def rebase_span(opening, draft, current):
    u = stations(np.asarray(draft)); before = stations(np.asarray(opening)); now = stations(np.asarray(current))
    old = np.column_stack([np.interp(u, before, np.asarray(opening)[:, axis]) for axis in range(3)])
    new = np.column_stack([np.interp(u, now, np.asarray(current)[:, axis]) for axis in range(3)])
    result = new + np.asarray(draft) - old
    result[0], result[-1] = current[0], current[-1]
    return result


def remap(raw, point_map, transform=None, attachments=''):
    payload = decode(raw); old = [row['sample_id'] for row in payload['samples']]
    new = {key: str(uuid4()) for key in old}
    for row in payload['samples']:
        row['sample_id'] = new[row['sample_id']]
        if transform is not None: row['co'] = list(transform(row['co']))
    for row in payload['structural']:
        row.update(point_id=point_map[row['point_id']], sample_id=new[row['sample_id']], occurrence_id=str(uuid4()))
    payload['attachment_digest'] = pair_digest(payload, attachments)
    return encode(payload)
