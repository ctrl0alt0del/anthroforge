"""Atomic RFC 6902 add/remove/replace/test subset."""
from .codec import decode
from .errors import require, AuthoringError

PROTECTED = {"dsl", "version", "document_id", "revision", "$schema"}


def apply_patch(document, operations):
    result = decode(document)
    for operation in operations:
        parts = tokens(operation["path"])
        require(parts and parts[0] not in PROTECTED, "PROTECTED_METADATA", pointer=operation["path"])
        try:
            _apply(result, parts, operation)
        except (KeyError, IndexError, TypeError) as exc:
            raise AuthoringError("PATCH_PATH", str(exc), operation["path"]) from exc
    return result


def tokens(pointer):
    require(not pointer or pointer.startswith("/"), "PATCH_POINTER")
    parts = pointer.split("/")[1:]
    for part in parts:
        require("~" not in part.replace("~0", "").replace("~1", ""), "PATCH_POINTER")
    return [part.replace("~1", "/").replace("~0", "~") for part in parts]


def _index(node, key, append=False):
    if not isinstance(node, list):
        return key
    if append and key == "-":
        return len(node)
    require(key.isdigit() and str(int(key)) == key, "PATCH_INDEX")
    index = int(key)
    require(index < len(node) + int(append), "PATCH_INDEX")
    return index


def _apply(document, parts, operation):
    node = document
    for key in parts[:-1]:
        node = node[_index(node, key)]
    op = operation["op"]
    key = _index(node, parts[-1], op == "add")
    if op == "test":
        require(_equal(node[key], operation["value"]), "PATCH_TEST", pointer=operation["path"])
    elif op == "remove":
        del node[key]
    elif op == "add" and isinstance(node, list):
        node.insert(key, operation["value"])
    else:
        require(op == "add" or key in node if isinstance(node, dict) else True, "PATCH_PATH")
        node[key] = operation["value"]


def _equal(first, second):
    if isinstance(first, bool) != isinstance(second, bool):
        return False
    if isinstance(first, dict) and isinstance(second, dict):
        return first.keys() == second.keys() and all(_equal(first[k], second[k]) for k in first)
    if isinstance(first, list) and isinstance(second, list):
        return len(first) == len(second) and all(_equal(a, b) for a, b in zip(first, second))
    return first == second
