"""Versioned native relationship policy ABI; no numerical Python fallback."""
import ctypes as C
from ..muscle_pairs import abi as pairs


class PolicyInput(C.Structure):
    _fields_ = [(k, C.c_uint64) for k in ('first', 'second', 'cover')]
    _fields_ += [(k, C.c_int) for k in ('excluded', 'invalid', 'offset', 'count')]


class PolicyResult(C.Structure):
    _fields_ = [('first', C.c_uint64), ('second', C.c_uint64), ('status', C.c_int), ('diagnostic', C.c_char * 128)]


class PolicyInputV2(C.Structure):
    _fields_ = [('legacy', PolicyInput), ('mode', C.c_int)]


def bind(library):
    try:
        if library.af_relationship_policy_version() != 1: raise RuntimeError('RELATIONSHIP_NATIVE_VERSION')
        submit = library.af_stack_submit_relationships_v1
        submit.argtypes = [*library.af_stack_submit.argtypes, C.POINTER(PolicyInput), C.c_int, pairs.IP, C.c_int]
        submit.restype = C.c_int
        summary = library.af_relationship_policy_summary
        summary.argtypes, summary.restype = [C.c_void_p, C.c_uint64, C.POINTER(PolicyResult), C.c_int], C.c_int
        return bind_explicit(library)
    except (AttributeError, OSError, RuntimeError) as error: raise RuntimeError('RELATIONSHIP_NATIVE_UNAVAILABLE: ' + str(error)) from error


def arrays(engine, domains, policies):
    keys = {(d.key.muscle, d.key.instance, d.key.side): engine.code('domain', d.key) for d in domains}
    rows, faces = [], []
    for policy in policies:
        if policy.mode == 'explicit' and not policy.cover: raise ValueError('RELATIONSHIP_ORDER_COVER')
        mode = ('automatic', 'requested', 'explicit').index(policy.mode) if policy.cover else 0
        rows.append(PolicyInputV2(PolicyInput(*(keys[k] for k in policy.pair), keys.get(policy.cover, 0),
            policy.excluded, policy.invalid, len(faces) // 2, len(policy.region)), mode))
        faces.extend(v for face in policy.region for v in face)
    return (PolicyInputV2 * len(rows))(*rows), (C.c_int64 * len(faces))(*faces)


def submit(engine, values, policies, arguments):
    rows, faces = arrays(engine, values, policies)
    return engine.library.af_stack_submit_relationships_v2(*arguments, rows, len(rows), faces, len(faces) // 2)


def enrich(engine, result):
    rows = (PolicyResult * len(engine.rows))()
    if engine.library.af_relationship_policy_summary(engine.handle, engine.generation, rows, len(rows)): raise RuntimeError('RELATIONSHIP_STALE_RESULT')
    names = ('allowed', 'excluded', 'manual_order_conflict', 'stale_selected_region')
    for pair, row in zip(result['pairs'], rows):
        pair['policy'] = dict(status=names[row.status], diagnostic=row.diagnostic.decode())
    effective(engine, result)


def bind_explicit(library):
    from ..muscle_stacking.abi import Order
    if library.af_explicit_order_version() != 1: raise RuntimeError('EXPLICIT_ORDER_NATIVE_VERSION')
    call = library.af_stack_submit_relationships_v2
    call.argtypes = [*library.af_stack_submit.argtypes, C.POINTER(PolicyInputV2), C.c_int, pairs.IP, C.c_int]
    call.restype = C.c_int
    call = library.af_relationship_effective_summary
    call.argtypes, call.restype = [C.c_void_p, C.c_uint64, C.POINTER(Order), C.c_int], C.c_int
    return library


def effective(engine, result):
    from ..muscle_stacking.abi import Order
    from ..muscle_stacking.native import order_record
    rows = (Order * len(engine.rows))()
    if engine.library.af_relationship_effective_summary(engine.handle, engine.generation, rows, len(rows)):
        raise RuntimeError('RELATIONSHIP_STALE_RESULT')
    for pair, row in zip(result['pairs'], rows): pair['effective_order'] = order_record(row, engine.domains)
