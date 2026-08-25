"""Safeguarded Anderson history for the feasible Fiber fixed-point map."""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class AndersonHistory:
    depth: int = 4
    signature: tuple = ()
    points: list = field(default_factory=list)
    residuals: list = field(default_factory=list)

    def reset(self, signature=()):
        self.signature = tuple(signature); self.points.clear(); self.residuals.clear()

    def propose(self, points, mapped, signature):
        if tuple(signature) != self.signature: self.reset(signature)
        residual = np.asarray(mapped) - np.asarray(points)
        if not self._append(points, residual): return np.asarray(mapped), False
        return _proposal(self.points, self.residuals, mapped, residual)

    def _append(self, points, residual):
        value = np.asarray(points, dtype=np.float64).reshape(-1).copy()
        if self.points and np.array_equal(value, self.points[-1]): return False
        self.points.append(value); self.residuals.append(residual.reshape(-1).copy())
        del self.points[:-self.depth - 1]; del self.residuals[:-self.depth - 1]
        return True


def _proposal(points, residuals, mapped, residual):
    if len(points) < 3: return np.asarray(mapped), False
    dx = np.column_stack([b - a for a, b in zip(points[:-1], points[1:])])
    df = np.column_stack([b - a for a, b in zip(residuals[:-1], residuals[1:])])
    coefficients = _coefficients(df, residual.reshape(-1))
    if coefficients is None: return np.asarray(mapped), False
    value = np.asarray(mapped).reshape(-1) - (dx + df) @ coefficients
    return value.reshape(np.asarray(mapped).shape), bool(np.isfinite(value).all())


def _coefficients(differences, residual):
    scale = max(1.0, float(np.linalg.norm(differences, ord=2)))
    regularized = np.vstack((differences, 1.0e-8 * scale * np.eye(differences.shape[1])))
    target = np.concatenate((residual, np.zeros(differences.shape[1])))
    try: value = np.linalg.lstsq(regularized, target, rcond=1.0e-10)[0]
    except np.linalg.LinAlgError: return None
    return value if np.isfinite(value).all() and np.linalg.norm(value) <= 10.0 else None
