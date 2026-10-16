from .constants import DEFAULT_TARGET_QUADS, MAX_TARGET_QUADS, MIN_TARGET_QUADS
from .refinement import normalized_strategy
from .model import TopologySettings


def default_settings_payload():
    return settings_payload(TopologySettings())


def settings_payload(settings):
    return {
        "target_quad_count": int(settings.target_quad_count),
        "symmetry_mode": str(settings.symmetry_mode),
        "custom_origin": list(settings.custom_origin),
        "custom_normal": list(settings.custom_normal),
        "refinement_strategy": str(settings.refinement_strategy),
        "backend": str(settings.backend),
    }


def settings_from_payload(payload):
    data = dict(payload or {})
    target = clamp_target(data.get("target_quad_count", DEFAULT_TARGET_QUADS))
    mode = str(data.get("symmetry_mode", "X") or "X").upper()
    origin = tuple(float(x) for x in data.get("custom_origin", (0, 0, 0)))
    normal = tuple(float(x) for x in data.get("custom_normal", (1, 0, 0)))
    strategy = normalized_strategy(data.get("refinement_strategy"))
    backend = str(data.get("backend", "QUADWILD"))
    if backend not in {"QUADWILD", "INSTANT"}: raise ValueError("Unknown topology backend.")
    return TopologySettings(target, mode, origin, normal, strategy, backend)


def clamp_target(value):
    return min(MAX_TARGET_QUADS, max(MIN_TARGET_QUADS, int(value)))
