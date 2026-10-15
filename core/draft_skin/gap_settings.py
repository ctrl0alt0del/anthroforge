"""Gap policy shared by capture, workers, and update invalidation."""
import hashlib
import json
import math


def effective_gap(source, settings):
    limit = settings.gap_limit_ratio if source.gap_limit_ratio < 0 else source.gap_limit_ratio
    strength = settings.gap_strength if source.gap_strength < 0 else source.gap_strength
    if not math.isfinite(limit) or limit < 0 or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("Draft skin gap settings must be finite; limit >= 0 and strength in [0, 1].")
    return float(limit), float(strength)


def gap_signature(capture):
    policies = [(s.entity_type, s.entity_id, s.mirror_role, *effective_gap(s, capture.settings))
                for s in capture.sources]
    payload = (2, capture.settings.gap_limit_ratio, capture.settings.gap_strength, policies)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def record_gap(record, settings):
    if record is None or getattr(record, "skin_gap_mode", "INHERIT") != "OVERRIDE":
        return settings.gap_limit_ratio, settings.gap_strength
    return float(record.skin_gap_limit_percent) / 100, float(record.skin_gap_strength_percent) / 100
