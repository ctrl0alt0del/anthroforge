"""Fiber V3 diagnostics layered on the shared numeric contracts."""

from dataclasses import asdict, dataclass
from math import isfinite

from ..fiber_numeric_contracts import FiberNumericDiagnostics


@dataclass(frozen=True)
class V3Diagnostics(FiberNumericDiagnostics):
    true_length: float = 0.0
    fidelity_energy: float = 0.0
    spacing_energy: float = 0.0
    effective_curvature_weight: float = 0.0
    segment_cv: float = 0.0
    regularization_initial: float = 0.0
    regularization_final: float = 0.0
    regularization_increases: int = 0
    regularization_decreases: int = 0
    span_terminations: tuple = ()
    shortcut_mode: str = "OFF"
    shortcut_attempts: int = 0
    shortcut_accepted: int = 0
    interactive_checkpoint: bool = False
    controller: str = "PYTHON"

    def __post_init__(self):
        super().__post_init__()
        _validate_v3_diagnostics(self)


def v3_diagnostics(base, **values):
    payload = asdict(base); payload.update(values)
    return V3Diagnostics(**payload)


def _validate_v3_diagnostics(value):
    names = ("true_length", "fidelity_energy", "spacing_energy", "segment_cv",
             "regularization_initial", "regularization_final")
    if any(not isfinite(float(getattr(value, name))) for name in names):
        raise ValueError("V3 diagnostics must be finite")
    if value.effective_curvature_weight != 0.0:
        raise ValueError("V3 curvature must remain zero")
    if value.controller not in ("PYTHON", "NATIVE"):
        raise ValueError("V3 controller must be PYTHON or NATIVE")
