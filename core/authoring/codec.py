"""Strict, deterministic JSON ingress and content identity."""
import hashlib
import json
import math
from .errors import AuthoringError, require


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_KEY", key)
        result[key] = value
    return result


def _constant(value):
    raise AuthoringError("NONFINITE_NUMBER", value)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode(value, max_bytes=16_000_000):
    try:
        text = value if isinstance(value, str) else encode(value)
        require(len(text.encode("utf-8")) <= max_bytes, "REQUEST_TOO_LARGE")
        result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _depth(result)
        return result
    except (json.JSONDecodeError, RecursionError, TypeError, OverflowError) as exc:
        raise AuthoringError("INVALID_JSON", str(exc)) from exc
    except ValueError as exc:
        if isinstance(exc, AuthoringError):
            raise
        raise AuthoringError("INVALID_JSON", str(exc)) from exc


def _depth(value, level=0):
    require(level < 96, "REQUEST_TOO_DEEP")
    require(not isinstance(value, float) or math.isfinite(value), "NONFINITE_NUMBER")
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for item in children:
        _depth(item, level + 1)


def digest(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()
