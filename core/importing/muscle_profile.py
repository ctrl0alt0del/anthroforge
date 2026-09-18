"""Validate profile snapshots before RNA assignment; copied identity stays new."""
from ..vcp.muscle_section_profile import PROFILE_FIELDS, SectionProfileSpec, canonical_profile, profile_properties, scale_profile


def prepared_properties(values, geometry_scale=1):
    result = dict(values or {})
    result.pop("af_authoring_profile_receipt", None)
    result.pop("af_authoring_muscle_creation", None)
    if result.get("section_profile_version") != 1:
        return result
    spec = SectionProfileSpec(*(result.get(key, getattr(SectionProfileSpec(), field))
        for key, field in zip(PROFILE_FIELDS, ("version", "depths", "peaks", "roundness", "direction"))))
    result.update(profile_properties(scale_profile(canonical_profile(spec), geometry_scale)))
    return result
