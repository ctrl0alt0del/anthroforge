"""Versioned structural and semantic validation entry points."""
from . import schema, semantics, trims, extensions, anchor_contract
from .errors import AuthoringError, require


def document(data):
    schema.validate(data)
    anchor_contract.validate(data)
    if data.get("version") == "0.4.0":
        return data
    return legacy_document(data)


def legacy_document(data):
    try:
        semantics.semantic_check(data)
        _shape_ranges(data)
        extensions.validate(data)
        for region in data["regions"].values():
            if region["definition"].get("trim_uv"):
                trims.triangulate(region["definition"]["trim_uv"])
    except AuthoringError:
        raise
    except (KeyError, TypeError, IndexError) as exc:
        raise AuthoringError("INVALID_REFERENCE", str(exc)) from exc
    return data


def request(data):
    schema.validate(data, "protocol")
    require(data["message_type"] == "request", "EXPECTED_REQUEST")
    if "document" in data["params"]:
        document(data["params"]["document"])
    return data


def _shape_ranges(data):
    for preset in data["volume_presets"].values():
        for check in preset["shape_checks"]:
            require(check["u_range"][0] <= check["u_range"][1], "SHAPE_INTERVAL_REVERSED")
    for policy in data["policies"].values():
        rule = policy["refinement"]
        require(rule["method"] == "none" or rule["max_attempts"] >= rule["max_added_fibers"], "REFINEMENT_BUDGET")
