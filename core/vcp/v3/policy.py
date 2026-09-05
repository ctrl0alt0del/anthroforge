"""Immutable accepted Fiber V3 numerical policy."""

from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import sha256
import json


class V3ShortcutMode(str, Enum):
    OFF = "OFF"
    SHADOW = "SHADOW"
    ON = "ON"


@dataclass(frozen=True)
class V3ProductionPolicy:
    true_length_irls: bool = True
    true_length_epsilon_ratio: float = 1.0e-4
    adaptive_quality: bool = True
    sqp_regularization_ratio: float = 1.0e-6
    adaptive_regularized_sqp: bool = True
    fidelity_scale: float = 0.01
    shortcut_mode: V3ShortcutMode = V3ShortcutMode.OFF

    def __post_init__(self):
        object.__setattr__(self, "shortcut_mode", V3ShortcutMode(self.shortcut_mode))
        _validate_policy(self)

    def fingerprint(self):
        payload = json.dumps(_plain_policy(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


def _plain_policy(policy):
    values = asdict(policy); values["shortcut_mode"] = policy.shortcut_mode.value
    return values


def _validate_policy(policy):
    if policy.fidelity_scale != 0.01: raise ValueError("V3 fidelity scale is fixed")
    if not policy.true_length_irls or not policy.adaptive_quality:
        raise ValueError("V3 accepted objective cannot be disabled")
    if not policy.adaptive_regularized_sqp:
        raise ValueError("V3 adaptive regularization cannot be disabled")


V3_PRODUCTION_POLICY = V3ProductionPolicy()


def accepted_v3_request(request, policy=V3_PRODUCTION_POLICY):
    settings = replace(request.settings, curvature_weight=0.0,
                       fidelity_weight=request.settings.fidelity_weight * policy.fidelity_scale)
    return replace(request, settings=settings)
