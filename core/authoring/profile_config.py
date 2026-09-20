"""Canonical native profile wire configuration shared by UI and authoring."""
from ..vcp.muscle_section_profile import SectionProfileSpec, canonical_profile, profile_from_muscle, profile_properties
from .errors import require
from .legacy_config import normalize_legacy, legacy_values

MODES = {"control_point": "CTRL_POINT", "distributed": "DISTRIBUTED", "section_profile": "SECTION_PROFILE"}
DIRECTIONS = {"local": "LOCAL", "smooth": "SMOOTH", "section": "SECTION"}
FIELDS = {"mode", "profile_version", "enabled", "flip_normals", "depths", "peaks", "roundness", "direction"}


def normalize(configuration):
    mode = configuration.get("mode")
    require(mode in MODES, "PROFILE_MODE_UNSUPPORTED", str(mode))
    if mode != "section_profile":
        return normalize_legacy(configuration)
    require(set(configuration) == FIELDS, "PROFILE_CONFIGURATION_INVALID")
    require(type(configuration["enabled"]) is bool and type(configuration["flip_normals"]) is bool, "PROFILE_CONFIGURATION_INVALID")
    require(configuration["direction"] in DIRECTIONS, "PROFILE_DIRECTION_UNSUPPORTED")
    spec = SectionProfileSpec(configuration["profile_version"], tuple(_depth(row) for row in configuration["depths"]),
        tuple(configuration["peaks"]), configuration["roundness"], DIRECTIONS[configuration["direction"]])
    return wire(canonical_profile(spec), configuration["enabled"], configuration["flip_normals"])


def _depth(row):
    require(isinstance(row, dict) and set(row) == {"value", "unit"} and row["unit"] == "scene", "PROFILE_DEPTH_UNIT")
    require(type(row["value"]) in (int, float), "PROFILE_PARAMETER_RANGE")
    return row["value"]


def wire(spec, enabled=True, flip=False):
    spec = canonical_profile(spec)
    return dict(mode="section_profile", profile_version=spec.version, enabled=bool(enabled), flip_normals=bool(flip),
        depths=[dict(value=value, unit="scene") for value in spec.depths], peaks=list(spec.peaks),
        roundness=spec.roundness, direction=spec.direction.lower())


def native_values(configuration):
    value = normalize(configuration)
    if value["mode"] != "section_profile":
        return legacy_values(value, MODES[value["mode"]])
    spec = SectionProfileSpec(value["profile_version"], tuple(row["value"] for row in value["depths"]),
                              tuple(value["peaks"]), value["roundness"], DIRECTIONS[value["direction"]])
    return dict(profile_properties(spec), inflation_enabled=value["enabled"], flip_normals=value["flip_normals"], inflation_mode="SECTION_PROFILE")


def current_configuration(muscle):
    if muscle.inflation_mode == "SECTION_PROFILE":
        return wire(profile_from_muscle(muscle), muscle.inflation_enabled, muscle.flip_normals)
    mode = next((wire for wire, native in MODES.items() if native == muscle.inflation_mode), None)
    require(mode is not None, "PROFILE_MODE_UNSUPPORTED")
    return dict(mode=mode)
