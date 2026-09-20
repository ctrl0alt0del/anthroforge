"""Material output domains: classify the base, interpolate both evaluated shells."""
from dataclasses import replace
import numpy as np

FIELDS = ('output_domain_mode', 'output_domain_origin', 'output_domain_normal', 'output_domain_keep_positive')
DEFAULTS = dict(zip(FIELDS, ('FULL', (0., 0., 0.), (0., 0., 1.), True)))


def configuration(muscle):
    if getattr(muscle, 'output_domain_mode', 'FULL') == 'FULL':
        return dict(mode='full')
    return normalize(dict(mode='plane', space='root_local',
        origin=list(muscle.output_domain_origin), normal=list(muscle.output_domain_normal),
        keep_positive=bool(muscle.output_domain_keep_positive)))


def normalize(value):
    if value == dict(mode='full'):
        return value
    keys = {'mode', 'space', 'origin', 'normal', 'keep_positive'}
    if set(value) != keys or value['mode'] != 'plane' or value['space'] != 'root_local':
        raise ValueError('DOMAIN_CONFIGURATION_INVALID')
    origin, normal = np.asarray(value['origin'], float), np.asarray(value['normal'], float)
    if origin.shape != (3,) or normal.shape != (3,) or not np.isfinite([origin, normal]).all():
        raise ValueError('DOMAIN_PLANE_INVALID')
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length < 1e-12 or type(value['keep_positive']) is not bool:
        raise ValueError('DOMAIN_PLANE_INVALID')
    return dict(value, origin=origin.tolist(), normal=(normal/length).tolist())


def native_values(value):
    value = normalize(value)
    if value['mode'] == 'full':
        return dict(DEFAULTS)
    return dict(zip(FIELDS, ('PLANE', value['origin'], value['normal'], value['keep_positive'])))


def capture(muscle):
    value = configuration(muscle)
    if value['mode'] == 'full':
        return None
    root = getattr(muscle, 'id_data', None)
    matrix = np.asarray(root.matrix_world, float) if root is not None else np.eye(4)
    point = (matrix @ np.r_[value['origin'], 1.])[:3]
    normal = np.linalg.solve(matrix[:3, :3].T, value['normal'])
    normal /= np.linalg.norm(normal)
    return dict(normal=tuple(normal), offset=float(point @ normal), keep_positive=value['keep_positive'])


def revision(base_revision, muscle):
    from ..authoring.codec import digest
    value = configuration(muscle)
    return base_revision if value['mode'] == 'full' else digest([base_revision, value, capture(muscle)])


def apply_result(request, result, face_parts=None):
    from .muscle_domain_clip import clip_domain
    from .muscle_numeric import _readonly_array, _invalid_result
    plane = getattr(request, 'output_domain', None)
    if plane is None or result.error:
        return result
    try:
        clipped = clip_domain(result.base_vertices, result.inflated_vertices, result.faces, plane, face_parts)
        arrays = {key: _readonly_array(getattr(clipped, key), dtype, shape) for key, dtype, shape in
                  (('base_vertices', float, (-1, 3)), ('inflated_vertices', float, (-1, 3)), ('faces', int, (-1, 3)),
                   ('source_faces', int, (-1,)), ('face_parts', int, (-1,)))}
        return replace(result, **arrays, row_count=0, column_count=0)
    except (ValueError, RuntimeError) as error:
        return _invalid_result(request.muscle_id, 'DOMAIN_EVALUATION_FAILED: '+str(error))


def apply_batch(requests, batch):
    return replace(batch, results=tuple(apply_result(request, result, np.zeros(len(result.faces), dtype=int))
                                       for request, result in zip(requests, batch.results)))
