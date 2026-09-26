"""One batched constraint solve; Python owns ABI packing, never optimization."""
import ctypes as ct
from time import perf_counter
import numpy as np
from . import shape_transfer_native as legacy
from .errors import require

KINDS = dict(attachment=0, shape=1, guide=2, clearance=3, protection=4)
DP, IP = legacy.DP, legacy.IP


class Rule(ct.Structure):
    _fields_ = [(k, ct.c_int) for k in ('kind', 'enabled', 'bins_u', 'bins_v')]
    _fields_ += [(k, IP) for k in ('selected', 'allowed', 'intended', 'worlds')]
    _fields_ += [(k, DP) for k in ('targets', 'axes')]
    _fields_ += [(k, ct.c_double) for k in ('weight', 'falloff', 'gap', 'tolerance', 'min_coverage')]


class Input(ct.Structure):
    _fields_ = [('abi', ct.c_int), ('count', ct.c_int), ('base', ct.POINTER(legacy.Input)), ('rules', ct.POINTER(Rule)), ('owners', IP)]
    _fields_ += [(k, DP) for k in ('factors', 'residuals', 'movement', 'summary', 'coverage')]


def array(value, integer=False):
    return np.ascontiguousarray(value, dtype=np.int32 if integer else np.float64)


def pointer(value):
    return value.ctypes.data_as(IP if value.dtype == np.int32 else DP)


def rule_arrays(rule, n, bones):
    selected, allowed, intended = (np.zeros(n, np.int32) for _ in range(3))
    selected[array(rule['indices'], True)] = 1; allowed[array(rule['allowed'], True)] = 1
    intended[array(rule.get('intended', rule['indices']), True)] = 1
    worlds = array([b.identity in rule.get('obstacle_instance_ids', []) for b in bones] or [0], True)
    targets = array(rule.get('targets', np.zeros((n, 3)))); coverage = rule.get('coverage', {})
    return [selected, allowed, intended, worlds, targets, array(coverage.get('axes', [[1, 0, 0], [0, 1, 0]]))]


def pack_rule(rule, arrays):
    bins = rule.get('coverage', {}).get('stations', [1, 1])
    return Rule(KINDS[rule['type']], rule.get('enabled', True), *map(int, bins), *map(pointer, arrays),
                rule.get('weight', 1.), rule.get('falloff', 0.), rule.get('clearance', 0.), rule['tolerance'],
                rule.get('coverage', {}).get('minimum_fraction', 0.))


def pack_base(source, initial, faces, fixed, worlds, settings, reflection):
    inputs = [array(source), array(initial), array(fixed, True), array(faces, True)]
    outputs = [np.zeros_like(inputs[0]), np.zeros(len(source)), np.zeros_like(inputs[0]), np.zeros(13)]
    handles = (ct.c_void_p*len(worlds))(*[w.handle for w in worlds])
    values = [settings[k] for k in ('radius_fraction', 'cluster_radius_fraction', 'bridge_fraction', 'shape_strength', 'collision_strength', 'clearance', 'convergence', 'far_influence')]
    base = legacy.Input(1, len(source), len(faces), len(worlds), reflection, int(settings['max_iterations']),
                        *map(pointer, inputs), handles, *values, *map(pointer, outputs))
    return base, inputs, outputs, handles


def fit(source, initial, faces, fixed, bones, rules, owners, settings=None, reflection=1):
    require(set(settings or {}) <= {'max_iterations', 'cluster_radius_fraction', 'convergence'}, 'TRANSFER_CONSTRAINT_SETTINGS')
    settings = dict(legacy.DEFAULTS, **(settings or {})); worlds = []
    legacy.validate(source, initial, faces, fixed, settings, reflection)
    validate_rules(rules, owners, len(source))
    require(0 <= len(bones) <= 32 and len(rules)*len(source) <= 4000000, 'TRANSFER_CONSTRAINT_BUDGET')
    try:
        for bone in bones:
            worlds.append(legacy.world(bone))
        return calculate(source, initial, faces, fixed, worlds, bones, rules, owners, settings, reflection)
    finally:
        for world in worlds:
            world.close()


def calculate(source, initial, faces, fixed, worlds, bones, records, owners, settings, reflection):
    base, _inputs, outputs, _handles = pack_base(source, initial, faces, fixed, worlds, settings, reflection)
    data = [rule_arrays(row, len(source), bones) for row in records]
    rules = (Rule*len(records))(*[pack_rule(row, arrays) for row, arrays in zip(records, data)])
    result = [np.zeros((len(records), len(source))) for _ in range(3)]
    result += [np.zeros((len(records), 8)), np.zeros((len(records), 32))]; owners = array(owners, True)
    args = Input(1, len(records), ct.pointer(base), rules, pointer(owners), *map(pointer, result))
    elapsed = invoke(args, records, result[3])
    require(all(np.isfinite(a).all() for a in outputs+result), 'TRANSFER_CONSTRAINT_NONFINITE')
    fitting = legacy.statistics(outputs[3], settings, elapsed)
    fitting.update(method='indexed_local_constraints.v1', curvature_preservation='not_constrained', weight_normalization='common_rest_extent_squared', settings={k: settings[k] for k in ('max_iterations', 'cluster_radius_fraction', 'convergence')})
    return dict(vertices=outputs[2], rest=outputs[0], influence=outputs[1], fitting=fitting, constraint_arrays=result)


def invoke(args, records, summary):
    lib = legacy.load_native()
    require(hasattr(lib, 'af_transfer_constraints_fit'), 'TRANSFER_CONSTRAINT_NATIVE_UNAVAILABLE', 'Rebuild the native library and restart Blender.')
    method = lib.af_transfer_constraints_fit; method.argtypes = [ct.POINTER(Input)]; method.restype = ct.c_int
    started = perf_counter(); code = method(ct.byref(args))
    locations = [dict(id=r.get('id', str(i)), packed_vertex=int(summary[i, 4]-1)) for i, r in enumerate(records) if summary[i, 4] > 0]
    require(code != 4, 'TRANSFER_CONSTRAINT_CONFLICT', 'Exact targets disagree, or positive clearance conflicts with an exact target: '+str(locations))
    require(code == 0, 'TRANSFER_CONSTRAINT_NATIVE_FAILED', str(code))
    return perf_counter()-started


def validate_rules(rules, owners, n):
    require(1 <= len(rules) <= 128 and np.asarray(owners).shape == (n,), 'TRANSFER_CONSTRAINT_BUDGET')
    require(np.isfinite(owners).all() and np.equal(owners, np.floor(owners)).all(), 'TRANSFER_CONSTRAINT_OWNER')
    for row in rules:
        require(row['type'] in KINDS, 'TRANSFER_CONSTRAINT_TYPE')
        for key in ('indices', 'allowed', 'intended'):
            ids = np.asarray(row.get(key, row['indices']))
            require(ids.ndim == 1 and len(ids) and np.isfinite(ids).all() and np.equal(ids, np.floor(ids)).all(), 'TRANSFER_SHAPE_INDEX')
            require(ids.min() >= 0 and ids.max() < n, 'TRANSFER_SHAPE_INDEX')
        require('targets' not in row or np.asarray(row['targets']).shape == (n, 3), 'TRANSFER_CONSTRAINT_TARGETS')
        require(np.asarray(row.get('coverage', {}).get('axes', np.eye(3)[:2])).shape == (2, 3), 'TRANSFER_CONSTRAINT_COVERAGE_AXES')
