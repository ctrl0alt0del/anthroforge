"""Validate profile snapshots before RNA assignment; copied identity stays new."""
from ..vcp.muscle_section_profile import PROFILE_FIELDS, SectionProfileSpec, canonical_profile, profile_properties, scale_profile


def prepared_properties(values, geometry_scale=1):
    result = dict(values or {})
    result.pop("af_authoring_profile_receipt", None)
    result.pop("af_authoring_envelope_receipt", None)
    result.pop("af_authoring_muscle_creation", None)
    result.pop('af_authoring_domain_receipt', None)
    result = _smoothing_properties(_domain_properties(result, geometry_scale), geometry_scale)
    if result.get("section_profile_version") != 1:
        return result
    spec = SectionProfileSpec(*(result.get(key, getattr(SectionProfileSpec(), field))
        for key, field in zip(PROFILE_FIELDS, ("version", "depths", "peaks", "roundness", "direction"))))
    result.update(profile_properties(scale_profile(canonical_profile(spec), geometry_scale)))
    return result


def _domain_properties(values, scale):
    from types import SimpleNamespace
    from ..vcp.muscle_output_domain import configuration, native_values
    if values.get('output_domain_mode', 'FULL') == 'FULL':
        return values
    domain = configuration(SimpleNamespace(**values))
    domain['origin'] = [value*float(scale) for value in domain['origin']]
    return dict(values, **native_values(domain))


def _smoothing_properties(values, scale):
    from types import SimpleNamespace
    from ..vcp.height_smoothing import capture, properties
    from dataclasses import asdict
    if not any(key.startswith('inflation_smoothing_') for key in values): return values
    spec = asdict(capture(SimpleNamespace(**values)))
    for key in ('radius', 'max_change'): spec[key] *= scale
    return dict(values, **properties(spec))
