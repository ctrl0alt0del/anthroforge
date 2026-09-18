"""Deterministic coordinate search; inflation fitting never adds fibers."""
from copy import deepcopy
import numpy as np
from .native_geometry import rebuild
from .errors import require
from .model import Budget
from .metrics import sections, closure

KEYS = {'max_inflation': 'amount', 'radius': 'radius', 'direction_depth': 'direction_depth', 'boundary_strength': 'strength', 'boundary_band': 'across', 'boundary_power': 'power'}
LIMITS = {'max_inflation': (0., 10.), 'radius': (.001, 100.), 'direction_depth': (.0001, 10.), 'boundary_strength': (0., 1.), 'boundary_band': (0., .5), 'boundary_power': (.1, 8.)}


def metrics(output):
    shape = (len(output['u']), len(output['s']), 3)
    base, surface = np.array(output['base']).reshape(shape), np.array(output['inflated']).reshape(shape)
    heights = np.linalg.norm(surface-base, axis=2)
    column = int(np.argmax(heights.max(axis=0)))
    return dict(height=float(heights.max()), width=max(r['width'] for r in sections(output)), belly_position=float(output['s'][column]))


def errors(values, targets):
    rows = []
    for target in targets:
        metric = target['metric']
        if metric not in values:
            rows.append(dict(metric=metric, state='unsupported', hard=target['hard'], reason='A supported closure is required for this metric.'))
            continue
        low, high = target['range']
        require(high > low, 'TARGET_RANGE_INVALID')
        residual = max(low-values[metric], 0, values[metric]-high)/(high-low)
        rows.append(dict(metric=metric, state='resolved' if residual == 0 else 'unresolved', achieved=values[metric], residual=residual, hard=target['hard']))
    return rows


def score(rows):
    hard = sum(r.get('residual', float('inf')) for r in rows if r['hard'])
    soft = sum(r.get('residual', float('inf'))**2 for r in rows if not r['hard'])
    return hard, soft


def evaluate(output, config, targets):
    value = deepcopy(output)
    value.update(rebuild(output, config), config=config)
    measurements = metrics(value)
    for target in targets:
        if target['metric'] in ('area', 'volume') and target['closure'] != 'none':
            measurements.update(closure(value, target['closure']))
    return value, errors(measurements, targets)


def fit(output, shape, budget=None):
    budget = budget or Budget()
    spec = shape['fitting']
    require(output["config"]["mode"] != "section_profile" or not spec["enabled"], "PROFILE_FITTING_UNSUPPORTED")
    best, rows = evaluate(output, deepcopy(output['config']), shape['targets'])
    count, step = 1, spec['step']
    if spec['enabled']:
        while count < spec['max_evaluations'] and score(rows) != (0, 0) and step > 1e-7:
            improved, count = search(best, rows, shape, step, count, budget)
            if improved is None:
                step /= 2
            else:
                best, rows = improved
    best['fitting'] = dict(evaluations=count, achieved=metrics(best), residuals=rows, state='resolved' if all(r['state'] == 'resolved' for r in rows) else 'unresolved', fibers_preserved=len(best['fibers']))
    return best


def search(best, rows, shape, step, count, budget):
    for key in shape['fitting']['parameters']:
        for sign in (-1, 1):
            if count >= shape['fitting']['max_evaluations']:
                return None, count
            budget.check()
            config = changed(best['config'], key, sign*step)
            candidate, residuals = evaluate(best, config, shape['targets'])
            count += 1
            if score(residuals) < score(rows):
                return (candidate, residuals), count
    return None, count


def changed(original, key, delta):
    require(key in KEYS, 'FITTING_PARAMETER_UNSUPPORTED')
    config = deepcopy(original)
    target = config['boundary'] if key.startswith('boundary_') else config
    field = KEYS[key]
    require(field in target, 'FITTING_PARAMETER_UNAVAILABLE')
    target[field] = float(np.clip(target[field]+delta, *LIMITS[key]))
    return config
