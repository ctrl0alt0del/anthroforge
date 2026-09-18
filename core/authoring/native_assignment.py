"""Verify RNA assignments component-wise, allowing representation rounding only."""
import numpy as np
from .errors import require


def assign_checked(item, key, value):
    setattr(item, key, value)
    actual = getattr(item, key)
    if isinstance(value, (str, bool, int)):
        require(actual == value, "NATIVE_PARAMETER_RANGE", key)
    else:
        expected, received = np.asarray(value), np.asarray(actual)
        require(expected.shape == received.shape and np.isfinite(received).all() and
                np.all(np.abs(received - expected) <= np.maximum(1e-7, np.abs(expected)*1e-6)), "NATIVE_PARAMETER_RANGE", key)
