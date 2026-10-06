"""Apply approved scalar effects to full material sides before output cropping."""
from dataclasses import replace
from time import perf_counter
import numpy as np
from .height_smoothing import active


def specs(request):
    return request.part_specs if hasattr(request, 'assembly') else (request.spec,)


def enabled(request):
    sides = (*specs(request), *(request.envelope.secondary if request.envelope else ()))
    return (request.envelope is None or request.envelope.enabled) and any(active(s) for s in sides)


def stripped(request):
    parts = tuple(replace(s, smoothing=None) for s in specs(request))
    env = request.envelope
    if env: env = replace(env, secondary=tuple(replace(s, smoothing=None) for s in env.secondary))
    values = dict(envelope=env, output_domain=None)
    return replace(request, **values, **({'part_specs': parts} if hasattr(request, 'assembly') else {'spec': parts[0]}))


def execute(requests, backend, evaluate):
    start = perf_counter()
    raw = tuple(stripped(r) if enabled(r) else r for r in requests)
    batch = evaluate(raw, backend)
    results = tuple(apply(r, v) if enabled(r) and not v.error else v for r, v in zip(requests, batch.results))
    return replace(batch, results=results, elapsed_ms=(perf_counter()-start)*1000)


def apply(request, result):
    from .muscle_numeric import _invalid_result
    try: return _apply(request, result)
    except (ValueError, RuntimeError) as error: return _invalid_result(request.muscle_id, str(error))


def side(result, own, settings):
    from .height_smoothing_native import smooth
    reports = []
    labels = np.zeros(len(result.faces), dtype=np.int64) if result.face_parts is None else result.face_parts
    for index, spec in enumerate(settings):
        if not active(spec): continue
        own, report = smooth(result.base_vertices, own, result.faces, labels, index, spec.smoothing)
        reports.append(dict(part=index, **report))
    return replace(result, inflated_vertices=own), reports


def _apply(request, result):
    from .muscle_output_domain import apply_result
    from .muscle_envelope import _compose
    a, first = side(result, result.side_a if request.envelope else result.inflated_vertices, specs(request))
    a = apply_result(request, a, a.face_parts)
    if a.error: return a
    reports = dict(a=first)
    if request.envelope:
        b, reports['b'] = side(result, result.side_b, request.envelope.secondary)
        b = apply_result(request, b, b.face_parts)
        if b.error: return b
        a = _compose(request, a, b)
    return replace(a, diagnostics=dict(a.diagnostics or {}, height_smoothing=reports))
