from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

UNIT_CONTRACT_VERSION = 1
UNIT_STATE_DECLARED = "DECLARED"
UNIT_STATE_UNDECLARED = "UNDECLARED"
UNIT_VERSION_KEY = "af_unit_contract_version"
UNIT_STATE_KEY = "af_unit_contract_state"
METERS_PER_WORLD_UNIT_KEY = "af_meters_per_world_unit"


@dataclass(frozen=True)
class RootUnitContract:
    state: str
    version: int
    meters_per_world_unit: float | None


def _undeclared_contract():
    return RootUnitContract(UNIT_STATE_UNDECLARED, 0, None)


def _positive_version(value):
    try:
        version = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return version if version > 0 else 0


def _positive_scale(value):
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return scale if isfinite(scale) and scale > 0.0 else None


def _contract(state, version, scale):
    version = _positive_version(version)
    scale = _positive_scale(scale)
    if str(state or "") != UNIT_STATE_DECLARED or version != UNIT_CONTRACT_VERSION or scale is None:
        return _undeclared_contract()
    return RootUnitContract(UNIT_STATE_DECLARED, version, scale)


def contract_from_payload(payload):
    if not isinstance(payload, Mapping):
        return _undeclared_contract()
    return _contract(payload.get("state"), payload.get("version"),
                     payload.get("meters_per_world_unit"))


def resolve_unit_contract(root):
    if root is None or not hasattr(root, "get"):
        return _undeclared_contract()
    return _contract(root.get(UNIT_STATE_KEY), root.get(UNIT_VERSION_KEY),
                     root.get(METERS_PER_WORLD_UNIT_KEY))


def declare_unit_contract(root, meters_per_world_unit, version=UNIT_CONTRACT_VERSION):
    contract = _contract(UNIT_STATE_DECLARED, version, meters_per_world_unit)
    if contract.state != UNIT_STATE_DECLARED:
        raise ValueError("Unit contract requires a positive version and finite positive scale.")
    root[METERS_PER_WORLD_UNIT_KEY] = contract.meters_per_world_unit
    root[UNIT_VERSION_KEY] = contract.version
    root[UNIT_STATE_KEY] = contract.state
    return contract


def declare_si_unit_contract(root):
    return declare_unit_contract(root, 1.0, UNIT_CONTRACT_VERSION)


def unit_contract_payload(root):
    contract = resolve_unit_contract(root)
    if contract.state != UNIT_STATE_DECLARED:
        return None
    return {"state": contract.state, "version": contract.version,
            "meters_per_world_unit": contract.meters_per_world_unit}


def world_distance_in_meters(root, distance):
    contract = resolve_unit_contract(root)
    if contract.meters_per_world_unit is None:
        return None
    return float(distance) * contract.meters_per_world_unit


def physical_scale_label(root):
    contract = resolve_unit_contract(root)
    if contract.meters_per_world_unit is None:
        return "Physical scale undeclared; distances use Blender world units"
    return f"1 world unit = {contract.meters_per_world_unit:g} m"
