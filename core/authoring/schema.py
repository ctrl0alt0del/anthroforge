"""Offline validator for the keyword profile of our pinned schemas.

This is deliberately not a general JSON Schema implementation or remote resolver.
"""
import json
import re
import math
from functools import lru_cache
from pathlib import Path
from .errors import AuthoringError, require
from . import SUPPORTED_VERSIONS


@lru_cache(maxsize=6)
def bundled(name, version="0.2.0"):
    require(name in ("authoring", "protocol"), "UNKNOWN_SCHEMA")
    require(version in SUPPORTED_VERSIONS, "UNSUPPORTED_VERSION")
    suffix = "-" + version[:3] if version != "0.2.0" else ""
    result = json.loads((Path(__file__).parent / "schemas" / (name + suffix + ".schema.json")).read_text())
    audit(result)
    return result


def validate(value, name="authoring"):
    root = bundled(name, value.get("version", "0.2.0"))
    _check(value, root, root, "")


def _check(value, spec, root, path):
    if "$ref" in spec:
        return _check(value, root["$defs"][spec["$ref"].split("/")[-1]], root, path)
    if "oneOf" in spec:
        return _choice(value, spec["oneOf"], root, path)
    _scalar(value, spec, path)
    if isinstance(value, dict):
        _object(value, spec, root, path)
    elif isinstance(value, list):
        _array(value, spec, root, path)


def _choice(value, choices, root, path):
    errors, passed = [], 0
    for spec in choices:
        try:
            _check(value, spec, root, path)
            passed += 1
        except AuthoringError as exc:
            errors.append(exc)
    if not passed and errors:
        raise max(errors, key=lambda error: len(error.pointer))
    require(passed == 1, "SCHEMA_CHOICE", pointer=path)


def _type(value, kind):
    types = {"object": dict, "array": list, "string": str, "boolean": bool}
    if kind in ("number", "integer"):
        return type(value) in (int, float) and (type(value) is int or math.isfinite(value)) and (kind == "number" or value == int(value))
    return isinstance(value, types[kind])


def _scalar(value, spec, path):
    if "type" in spec:
        require(_type(value, spec["type"]), "SCHEMA_TYPE", pointer=path)
    if "enum" in spec:
        require(any(value == item and isinstance(value, bool) == isinstance(item, bool)
                    for item in spec["enum"]), "SCHEMA_ENUM", pointer=path)
    _bounds(value, spec, path)
    if isinstance(value, str):
        require(len(value) >= spec.get("minLength", 0), "SCHEMA_LENGTH", pointer=path)
        require("pattern" not in spec or re.search(spec["pattern"], value), "SCHEMA_PATTERN", pointer=path)


def _bounds(value, spec, path):
    if type(value) not in (float, int):
        return
    rules = {"minimum": lambda n: value >= n, "maximum": lambda n: value <= n,
             "exclusiveMinimum": lambda n: value > n, "exclusiveMaximum": lambda n: value < n}
    for name, rule in rules.items():
        require(name not in spec or rule(spec[name]), "SCHEMA_RANGE", pointer=path)


def _object(value, spec, root, path):
    for key in spec.get("required", ()):
        require(key in value, "SCHEMA_REQUIRED", pointer=path + "/" + key)
    for key, child in value.items():
        if "propertyNames" in spec:
            _check(key, spec["propertyNames"], root, path)
        child_spec = spec.get("properties", {}).get(key, spec.get("additionalProperties", {}))
        pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
        require(child_spec is not False, "SCHEMA_UNKNOWN_FIELD", pointer=pointer)
        _check(child, child_spec if isinstance(child_spec, dict) else {}, root, pointer)


def _array(value, spec, root, path):
    require(spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", float("inf")),
            "SCHEMA_LENGTH", pointer=path)
    for index, child in enumerate(value):
        _check(child, spec.get("items", {}), root, path + "/" + str(index))


def audit(spec):
    if isinstance(spec,bool):
        return
    supported = {"$schema","$id","$defs","$ref","title","description","type","oneOf","enum","properties","required",
                 "additionalProperties","propertyNames","items","minItems","maxItems","minLength","pattern",
                 "minimum","maximum","exclusiveMinimum","exclusiveMaximum"}
    require(not (set(spec)-supported), "UNSUPPORTED_SCHEMA_KEYWORD", str(set(spec)-supported))
    for group in ("$defs","properties"):
        for child in spec.get(group,{}).values():
            audit(child)
    for child in spec.get("oneOf",[]):
        audit(child)
    for key in ("items","propertyNames","additionalProperties"):
        if key in spec:
            audit(spec[key])
