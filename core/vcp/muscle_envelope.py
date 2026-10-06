"""Immutable envelope settings and evaluation of opposite material sides."""
from dataclasses import dataclass, replace
from time import perf_counter
import numpy as np


@dataclass(frozen=True)
class MuscleEnvelopeSpec:
    secondary: tuple
    enabled: bool = True
    reverse: bool = False
    version: int = 1


def execute(requests, backend):
    from .muscle_numeric import execute_muscle_batch, MuscleNumericBatchResult
    start = perf_counter(); results = []
    for request in requests:
        results.append(evaluate(request) if request.envelope else execute_muscle_batch((request,), backend).results[0])
    return MuscleNumericBatchResult(tuple(results), 'NATIVE_ENVELOPE_V1', (perf_counter()-start)*1000)


def evaluate(request):
    from .muscle_numeric import _invalid_result
    try: return _evaluate(request)
    except (ValueError, RuntimeError, AttributeError) as error:
        return _invalid_result(request.muscle_id, str(error))


def _evaluate(request):
    from .muscle_output_domain import apply_result
    if request.envelope.version != 1: raise ValueError('ENVELOPE_VERSION_UNSUPPORTED')
    first, second = _side_requests(request)
    a, b, timing = _timed_sides(first, second)
    if a.error or b.error: raise ValueError(a.error or b.error)
    if not np.array_equal(np.sort(a.faces, axis=1), np.sort(b.faces, axis=1)): raise ValueError("ENVELOPE_CORRESPONDENCE_INVALID")
    a, b = _canonical_results(request, a, b)
    labels = np.zeros(len(a.faces), dtype=int) if a.face_parts is None else a.face_parts
    a, b = apply_result(request, a, labels), apply_result(request, b, labels)
    if a.error or b.error: raise ValueError(a.error or b.error)
    _check_correspondence(a, b)
    result = _compose(request, a, b)
    result.diagnostics["timings_ms"] = timing
    return result


def _side_requests(request):
    from .branched_numeric import BranchedMuscleRequest
    env = request.envelope; common = dict(envelope=None, output_domain=None)
    specs = request.part_specs if isinstance(request, BranchedMuscleRequest) else (request.spec,)
    if len(env.secondary) != len(specs): raise ValueError('ENVELOPE_PART_MISMATCH')
    if any(s.closed_u or s.close_across_fibers or s.closed_v for s in (*specs, *env.secondary)):
        raise ValueError('ENVELOPE_DOMAIN_UNSUPPORTED')
    sides = tuple(tuple(replace(s, inflation_enabled=s.inflation_enabled and env.enabled,
        flip_normals=specs[i].flip_normals ^ env.reverse ^ bool(side)) for i, s in enumerate(values))
        for side, values in enumerate((specs, env.secondary)))
    if isinstance(request, BranchedMuscleRequest):
        return tuple(replace(request, **common, part_specs=values, assembly=replace(request.assembly,
            flip=request.assembly.flip ^ env.reverse ^ bool(side))) for side, values in enumerate(sides))
    return tuple(replace(request, **common, spec=values[0]) for values in sides)


def _side(request):
    from .muscle_profile_cache import cached, content_key
    if hasattr(request, 'assembly'):
        from .branched_surface import assemble
        base, faces = assemble(request.assembly)
        meta = (request.part_specs, request.assembly.flip, tuple((b.connection, b.along.tolist()) for b in request.assembly.branches))
        key = content_key(base, 'envelope-side-1', meta, faces.tolist())
    else: key = content_key(request.points, 'envelope-side-1', request.spec, request.orientation_parity)
    return replace(cached(key, lambda: _side_uncached(request)), muscle_id=request.muscle_id)


def _side_uncached(request):
    from .muscle_numeric import execute_muscle_batch
    if hasattr(request, 'assembly'):
        return execute_muscle_batch((request,), 'NATIVE').results[0]
    from .muscle_profile_numeric import prepare_profile
    result = prepare_profile(request, 'NATIVE', execute_muscle_batch)
    if result.error: return result
    grid = result.base_vertices.reshape(result.row_count, result.column_count, 3)
    return replace(result, inflated_vertices=_inflate(grid, request).reshape(-1, 3))


def _inflate(grid, request):
    from .muscle_envelope_native import section, legacy
    spec = request.spec
    if not spec.inflation_enabled: return grid.copy()
    if spec.inflation_mode != 'SECTION_PROFILE': return legacy(grid, spec)
    sign = request.orientation_parity * (-1 if spec.flip_normals else 1)
    return section(grid, spec.section_profile, sign)


def _compose(request, a, b):
    from .muscle_envelope_native import compose, diagnostics
    if hasattr(request, 'assembly'): flip = request.envelope.reverse
    else: flip = request.spec.flip_normals ^ request.spec.topology_flip_normals ^ request.envelope.reverse
    vertices, faces, sources, sides = compose(a.inflated_vertices, b.inflated_vertices, a.faces, flip)
    parts = np.zeros(len(a.faces), dtype=int) if a.face_parts is None else a.face_parts
    return replace(a, inflated_vertices=vertices, inflated_faces=faces, side_a=a.inflated_vertices,
        side_b=b.inflated_vertices, inflated_parts=parts[sources], inflated_sides=sides,
        inflated_sources=sources if a.source_faces is None else a.source_faces[sources], diagnostics=_diagnostics(a, b, vertices, faces, flip))


def faces_for(result, inflated=False):
    return result.inflated_faces if inflated and result.inflated_faces is not None else result.faces


def geometry(result):
    value = dict(base=result.base_vertices.tolist(), inflated=result.inflated_vertices.tolist(), faces=result.faces.tolist())
    if result.diagnostics is not None: value['diagnostics'] = result.diagnostics
    if result.side_a is not None:
        value.update(side_a=result.side_a.tolist(), side_b=result.side_b.tolist(),
                     inflated_faces=result.inflated_faces.tolist(), face_sides=result.inflated_sides.tolist(),
                     inflated_sources=result.inflated_sources.tolist(), diagnostics=result.diagnostics)
    return value


def _inactive_sides(request, a, b):
    primary = request.part_specs if hasattr(request, 'assembly') else (request.spec,)
    off = lambda specs: not request.envelope.enabled or all(not s.inflation_enabled or _zero(s) for s in specs)
    if off(primary): a = replace(a, inflated_vertices=a.base_vertices)
    if off(request.envelope.secondary): b = replace(b, inflated_vertices=b.base_vertices)
    return a, b


def _zero(spec):
    if spec.inflation_mode == 'SECTION_PROFILE': return not any(spec.section_profile.depths)
    return spec.inflation_max_value == 0


def _canonical_results(request, a, b):
    from .branched_surface import assemble
    faces = assemble(request.assembly)[1] if hasattr(request, 'assembly') else a.faces
    return _inactive_sides(request, replace(a, faces=faces), replace(b, faces=faces))


def _timed_sides(first, second):
    start = perf_counter(); a = _side(first); middle = perf_counter(); b = _side(second)
    return a, b, dict(side_a_with_preparation=(middle-start)*1000, side_b_with_preparation=(perf_counter()-middle)*1000)


def _diagnostics(a, b, vertices, faces, flip):
    from .muscle_envelope_native import diagnostics, side_diagnostics
    report = diagnostics(vertices, faces); sign = -1 if flip else 1
    report['side_a'] = side_diagnostics(a.base_vertices, a.inflated_vertices, a.faces, sign)
    report['side_b'] = side_diagnostics(b.base_vertices, b.inflated_vertices, b.faces, -sign)
    report['warnings'] = [f'{key}:{field}' for key in ('side_a', 'side_b')
                          for field in ('wrong_side_samples', 'large_normal_turns', 'degenerate_frames') if report[key][field]]
    report['warnings'] += [key for key in ('nonmanifold_edges', 'degenerate_faces') if report[key]]
    return report


def _check_correspondence(a, b):
    if not np.array_equal(a.base_vertices, b.base_vertices) or not np.array_equal(a.faces, b.faces):
        raise ValueError('ENVELOPE_CORRESPONDENCE_INVALID')
