"""Versioned vector submission, exact attachments and bounded diagnostics."""
import ctypes as C
import numpy as np
from ..muscle_pairs import abi as pairs
from ..muscle_relationships import native as relationships


class Settings(C.Structure):
    _fields_ = [(k, C.c_double) for k in ('blend', 'preservation', 'adjustment')]


class Exact(C.Structure):
    _fields_ = [('id', C.c_uint64), ('indices', pairs.IP), ('weights', pairs.DP), ('count', C.c_int), ('width', C.c_int)]


def bind(library):
    if not hasattr(library, 'af_vector_stacking_version') or library.af_vector_stacking_version() != 1:
        raise RuntimeError('STACK_VECTOR_NATIVE_UNAVAILABLE')
    call = library.af_vector_stack_submit_v1
    call.argtypes = [*library.af_stack_submit_relationships_v2.argtypes, C.POINTER(Settings), C.POINTER(Exact), C.c_int]
    call.restype = C.c_int
    call = library.af_vector_stack_metrics
    call.argtypes, call.restype = [C.c_void_p, C.c_uint64, C.c_uint64, pairs.DP, C.c_int], C.c_int
    return library


def exact_arrays(engine, domains):
    owned, records = [], []
    for d in domains:
        rows = d.material.constraints
        indices, weights = np.zeros((len(rows), 4), dtype=np.int64), np.zeros((len(rows), 4))
        for i, row in enumerate(rows):
            if not 1 <= len(row.indices) <= 4 or len(row.weights) != len(row.indices): raise ValueError('STACK_VECTOR_CONSTRAINT_WIDTH')
            indices[i, :len(row.indices)] = row.indices; weights[i, :len(row.weights)] = row.weights
        owned.extend((indices, weights))
        records.append(Exact(engine.code('domain', d.key), pairs.pointer(indices), pairs.pointer(weights), len(rows), 4))
    return (Exact*len(records))(*records), owned


def submit(engine, domains, policies, arguments, settings):
    rows, faces = relationships.arrays(engine, domains, policies)
    exact, owned = exact_arrays(engine, domains)
    config = Settings(settings.blend_distance, settings.preservation_weight, settings.smoothing_max_adjustment)
    return engine.library.af_vector_stack_submit_v1(*arguments, rows, len(rows), faces, len(faces)//2, C.byref(config), exact, len(exact))


def metrics(engine, identity):
    values = np.zeros(24)
    if engine.library.af_vector_stack_metrics(engine.handle, engine.generation, identity, pairs.pointer(values), len(values)):
        raise RuntimeError('STACK_VECTOR_STALE_RESULT')
    names = ('correspondence_ms', 'mapped_samples', 'multiple_matches', 'locality_ms', 'support_mapping_ms',
        'assembly_ms', 'piqp_ms', 'certification_error', 'remapped_support_error', 'attachment_error',
        'raw_maximum_displacement', 'final_maximum_displacement', 'far_region_movement', 'retained_displacement_ratio',
        'preparation_ms', 'total_ms', 'minimum_preservation_weight', 'maximum_preservation_weight',
        'far_vertices', 'blend_vertices', 'support_rows', 'contact_validated', 'baseline_assessed', 'solve_cache_reused')
    return dict(algorithm='vector-localized-v1', **dict(zip(names, values.tolist())))
