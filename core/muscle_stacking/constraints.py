"""Exact structural attachment rows; vector stacking enforces their weighted sums."""
from dataclasses import dataclass
import ctypes as C
import numpy as np
from ..muscle_pairs import abi


@dataclass(frozen=True)
class MaterialConstraint:
    identity: str
    indices: tuple
    weights: tuple
    reason: str = 'attachment'


def chart(across, along, mapping, queries, identities):
    a, b, uv = [np.ascontiguousarray(v, dtype=float) for v in (across, along, queries)]
    ids = np.ascontiguousarray(mapping, dtype=np.int64)
    if ids.shape != (len(a), len(b)) or uv.shape != (len(identities), 2): raise ValueError('STACK_CONSTRAINT_CHART_SIZE')
    indices = np.empty((len(uv), 4), dtype=np.int64); weights = np.empty((len(uv), 4))
    lib = abi.library()
    if lib.af_stack_constraint_capture_version() != 1: raise RuntimeError('STACK_CONSTRAINT_CAPTURE_UNAVAILABLE')
    call = lib.af_stack_chart_constraints
    call.argtypes = [abi.DP, C.c_int, abi.DP, C.c_int, abi.IP, abi.DP, C.c_int, abi.IP, abi.DP]; call.restype = C.c_int
    if call(abi.pointer(a), len(a), abi.pointer(b), len(b), abi.pointer(ids), abi.pointer(uv), len(uv), abi.pointer(indices), abi.pointer(weights)):
        raise ValueError('STACK_CONSTRAINT_CHART_INVALID')
    return tuple(MaterialConstraint(label, tuple(map(int, i)), tuple(map(float, w))) for label, i, w in zip(identities, indices, weights))


def fixed_indices(constraints, count):
    fixed = set()
    for row in constraints:
        if not row.indices or len(row.indices) != len(row.weights): raise ValueError('STACK_CONSTRAINT_SHAPE')
        if any(i < 0 or i >= count for i in row.indices): raise ValueError('STACK_CONSTRAINT_INDEX')
        if any(not np.isfinite(w) or w < 0 for w in row.weights) or abs(sum(row.weights)-1) > 1e-9:
            raise ValueError('STACK_CONSTRAINT_WEIGHTS')
        fixed.update(i for i, w in zip(row.indices, row.weights) if w > 0)
    return np.asarray(sorted(fixed), dtype=np.int64)
