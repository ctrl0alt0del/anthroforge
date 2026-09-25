"""Bounded damped least squares with analytic contact-distance derivatives."""
from time import perf_counter
import numpy as np
from .correction_field import build
from .errors import require


def regularization(field, settings):
    phi, edge = field['phi'], field['edges']
    rows = np.vstack((phi*.05, (phi[edge[:, 1]]-phi[edge[:, 0]])*settings.get('smoothness', 3.), np.eye(phi.shape[1])*.02))
    return rows, np.kron(rows @ field['null'], np.eye(3))


def signed_volume(vertices, faces):
    tri = vertices[faces]-vertices.mean(axis=0)
    return float(np.einsum('ij,ij->i', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()/6)


def volume_terms(vertices, basis, field, settings):
    faces = field['faces']; tri = vertices[faces]-vertices.mean(axis=0); gradient = np.zeros_like(vertices)
    for axis in range(3):
        np.add.at(gradient, faces[:, axis], np.cross(tri[:, (axis+1) % 3], tri[:, (axis+2) % 3])/6)
    factor = 1000*settings['influence_radius']/max(abs(field['volume']), 1e-20)
    residual = np.array([(signed_volume(vertices, faces)-field['volume'])*factor])
    return residual, (basis.T @ gradient).reshape(1, -1)*factor


def extra_terms(field, controls, settings):
    vertices, basis = field['vertices']+field['phi'] @ controls, field['phi'] @ field['null']
    residual, jacobian = volume_terms(vertices, basis, field, settings)
    if field.get('reverse') is not None:
        r, j = field['reverse'](vertices, basis); residual = np.r_[residual, r]; jacobian = np.vstack((jacobian, j))
    return residual, jacobian


def evaluate(x, field, oracles, settings, regular):
    controls = field['part']+field['null'] @ x.reshape(-1, 3)
    points = field['samples']+field['sample_basis'] @ controls
    basis = field['sample_basis'] @ field['null']; residual, jacobian = [], []
    for oracle in oracles:
        distance, gradient = oracle.distance(points)
        limit = field['limits'][oracle.identity]; active = distance < limit
        residual.append(np.minimum(distance-limit, 0)*1000)
        jacobian.append((basis[:, :, None]*gradient[:, None, :]*active[:, None, None]*1000).reshape(len(points), -1))
    residual.append((regular[0] @ controls).ravel()); jacobian.append(regular[1])
    r, j = extra_terms(field, controls, settings); residual.append(r); jacobian.append(j)
    return np.concatenate(residual), np.vstack(jacobian), controls


def trial(x, step, field, oracles, settings, regular, score):
    for scale in (1., .5, .25, .125, .0625, .03125):
        candidate = x+step*scale
        controls = field['part']+field['null'] @ candidate.reshape(-1, 3)
        if np.linalg.norm(field['phi'] @ controls, axis=1).max() > settings['max_displacement']:
            continue
        value = evaluate(candidate, field, oracles, settings, regular)
        if value[0] @ value[0] < score:
            return candidate, value
    return None


def step_for(field, value, settings, damping):
    residual, jacobian, _controls = value
    hessian = jacobian.T @ jacobian
    system = hessian+np.diag(np.maximum(np.diag(hessian), 1.)*damping)
    step = np.linalg.lstsq(system, -jacobian.T @ residual, rcond=1e-12)[0]
    movement = np.linalg.norm(field['phi'] @ field['null'] @ step.reshape(-1, 3), axis=1).max()
    return step*min(1., settings['influence_radius']*.25/max(movement, 1e-20))


def advance(x, value, damping, field, oracles, settings, regular):
    step = step_for(field, value, settings, damping)
    accepted = trial(x, step, field, oracles, settings, regular, value[0] @ value[0])
    if accepted is None:
        return x, value, damping*10
    return *accepted, max(damping*.3, 1e-6)


def optimize(field, oracles, settings):
    field['limits'] = {o.identity: np.minimum(o.distance(field['samples'])[0], 0)-settings['tolerance']*.1 if o.identity in settings.get('guard_instance_ids', []) else settings.get('fit_clearance', 0.)+settings['tolerance']*2 for o in oracles}
    x = np.zeros(field['null'].shape[1]*3); regular = regularization(field, settings)
    value = evaluate(x, field, oracles, settings, regular); start = perf_counter(); reason = 'iteration_budget'; damping = .01
    for iteration in range(settings.get('max_iterations', 60)):
        if perf_counter()-start > settings.get('max_seconds', 60):
            reason = 'time_budget'; break
        x, value, damping = advance(x, value, damping, field, oracles, settings, regular)
        if damping > 1e8:
            reason = 'stationary'; break
    return value[2], dict(iterations=iteration+1, stop_reason=reason, elapsed_seconds=perf_counter()-start, objective=float(value[0] @ value[0]))


def check_budget(field, oracles, reverse):
    rows = len(field['samples'])*len(oracles)+3*(len(field['phi'])+len(field['edges'])+field['phi'].shape[1])+1
    if reverse is not None:
        rows += sum(len(points) for points, _limits in reverse.groups)
    require(rows*field['null'].shape[1]*3 <= 20000000, 'CORRECTION_SOLVE_BUDGET')


def fit(vertices, faces, oracles, settings, fixed, contacts, reverse=None):
    inside = np.any([o.distance(vertices)[0] < settings.get('fit_clearance', 0.)+settings['tolerance'] for o in oracles if o.identity not in settings.get('guard_instance_ids', [])], axis=0)
    seeds = vertices[inside]
    if reverse is not None and len(reverse.seeds): seeds = np.vstack((seeds, reverse.seeds))
    if not len(seeds) and not contacts:
        return vertices.copy(), dict(stop_reason='already_clear', iterations=0), {}
    field = build(vertices, faces, settings, fixed, contacts, seeds)
    field.update(reverse=reverse, vertices=vertices, faces=faces, volume=signed_volume(vertices, faces))
    check_budget(field, oracles, reverse)
    controls, report = optimize(field, oracles, settings)
    output = vertices+field['phi'] @ controls
    report['max_displacement'] = float(np.linalg.norm(output-vertices, axis=1).max())
    serialized = dict(centers=field['centers'].tolist(), controls=controls.tolist(), settings=settings)
    return output, report, serialized
