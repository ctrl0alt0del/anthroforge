"""Bounded BiCGSTAB for the nonsymmetric positive mean-value Laplacian."""
import numpy as np
from .errors import require


def solve(apply, rhs):
    state = dict(x=np.zeros(len(rhs)), r=rhs.copy(), p=np.zeros(len(rhs)), v=np.zeros(len(rhs)), rho=1., alpha=1., omega=1.)
    threshold = 1e-10*max(1., np.linalg.norm(rhs))
    for _ in range(2048):
        if np.linalg.norm(state['r']) <= threshold:
            require(np.linalg.norm(apply(state['x'])-rhs) <= threshold*10, 'LAYOUT_CHART_SINGULAR')
            return state['x']
        step(state, apply, rhs, threshold)
    require(False, 'LAYOUT_CHART_BUDGET', 'Mean-value parameterization did not converge.')


def ratio(numerator, denominator):
    require(np.isfinite(denominator) and abs(denominator) > 1e-30, 'LAYOUT_CHART_SINGULAR')
    return float(numerator/denominator)


def step(state, apply, shadow, threshold):
    rho = float(shadow @ state['r'])
    beta = ratio(rho, state['rho'])*ratio(state['alpha'], state['omega'])
    p = state['r']+beta*(state['p']-state['omega']*state['v'])
    v = apply(p)
    alpha = ratio(rho, shadow @ v)
    s = state['r']-alpha*v
    if np.linalg.norm(s) <= threshold:
        state.update(x=state['x']+alpha*p, r=s)
        return
    t = apply(s)
    omega = ratio(t @ s, t @ t)
    state.update(x=state['x']+alpha*p+omega*s, r=s-omega*t, p=p, v=v, rho=rho, alpha=alpha, omega=omega)
