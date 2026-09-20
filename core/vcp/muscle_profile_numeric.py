"""Partition profiles before native packing and reuse immutable prepared bases."""
from dataclasses import replace
from time import perf_counter
from .muscle_section_profile import PROFILE_VERSION, apply_profile, canonical_profile
from .muscle_profile_frames import direction_field
from .muscle_profile_cache import cached, content_key

LEGACY_MODES = ("CTRL_POINT", "DISTRIBUTED")


def request_error(request):
    spec = request.spec
    if spec.inflation_mode not in (*LEGACY_MODES, "SECTION_PROFILE"):
        return "PROFILE_MODE_UNSUPPORTED: " + str(spec.inflation_mode)
    if request.orientation_parity != 1 and spec.inflation_mode != "SECTION_PROFILE":
        return "PROFILE_PARITY_UNSUPPORTED_MODE"
    if spec.inflation_mode == "SECTION_PROFILE" and (spec.closed_u or spec.close_across_fibers or spec.closed_v):
        return "PROFILE_DOMAIN_UNSUPPORTED: Section Profile requires an ordinary open loft."
    return ""


def execute_partitioned(requests, kind, execute):
    from .muscle_numeric import MuscleNumericBatchResult, _invalid_result
    started, results = perf_counter(), {}
    legacy = tuple(row for row in requests if not request_error(row) and row.spec.inflation_mode in LEGACY_MODES)
    batch = execute(legacy) if legacy else None
    if batch:
        results.update((id(row), result) for row, result in zip(legacy, batch.results))
    for row in requests:
        error = request_error(row)
        if error or row.spec.inflation_mode == "SECTION_PROFILE":
            results[id(row)] = _invalid_result(row.muscle_id, error) if error else profile_result(row, kind, execute)
    backend = kind + "+NUMPY_SECTION_PROFILE" if any(row.spec.inflation_mode == "SECTION_PROFILE" for row in requests) else kind
    return MuscleNumericBatchResult(tuple(results[id(row)] for row in requests), backend,
        (perf_counter()-started)*1000, batch.workers if batch else 1, batch.parallel if batch else False)


def prepared_key(request, backend):
    spec = request.spec
    return content_key(request.points, PROFILE_VERSION, backend, spec.target_count, spec.densify,
        spec.closed_u, spec.close_across_fibers, spec.topology_flip_normals)


def prepare_profile(request, backend, execute):
    spec = replace(request.spec, inflation_mode="CTRL_POINT", inflation_enabled=False, initialize_control=False,
                   section_profile=None)
    plain = replace(request, spec=spec, orientation_parity=1, output_domain=None)
    return cached(prepared_key(request, backend), lambda: execute((plain,)).results[0])


def profile_result(request, backend, execute):
    from .muscle_numeric import _invalid_result
    try:
        profile = canonical_profile(request.spec.section_profile)
        result = prepare_profile(request, backend, execute)
        if result.error:
            return replace(result, muscle_id=request.muscle_id)
        return evaluated_profile(request, result, profile, backend)
    except (ValueError, TypeError, AttributeError) as error:
        return _invalid_result(request.muscle_id, str(error))


def evaluated_profile(request, result, profile, backend):
    from .muscle_numeric import _readonly_array
    base = result.base_vertices.reshape(result.row_count, result.column_count, 3)
    spec, frames = request.spec, None
    if spec.inflation_enabled and any(profile.depths):
        key = (prepared_key(request, backend), profile.direction, request.orientation_parity, spec.flip_normals)
        frames = cached(key, lambda: direction_field(base, profile.direction))
    vertices = apply_profile(base, profile, spec.inflation_enabled, spec.flip_normals, request.orientation_parity, frames)
    return replace(result, muscle_id=request.muscle_id, inflated_vertices=_readonly_array(vertices, float, (-1, 3)))
