from dataclasses import dataclass

from .soft_tissue_model import BaseDomain, BoundaryMode, InflationMode, SolverMode, TissuePreset


@dataclass(frozen=True)
class PresetValues:
    domain: BaseDomain
    boundary: BoundaryMode
    inflation_mode: InflationMode
    relaxation_mode: SolverMode
    values: tuple[tuple[str, object], ...]
    attachments: tuple[tuple[str, str, float], ...]


def preset_values(preset):
    key = TissuePreset(str(getattr(preset, "value", preset)))
    return _PRESETS.get(key, _PRESETS[TissuePreset.CUSTOM])


def preset_dict(preset):
    return dict(preset_values(preset).values)


_PRESETS = {
    TissuePreset.CUSTOM: PresetValues(
        BaseDomain.SURFACE, BoundaryMode.HOST_SEALED, InflationMode.NORMAL,
        SolverMode.NONE, (), (),
    ),
    TissuePreset.CLOSED_BULK: PresetValues(
        BaseDomain.POINT, BoundaryMode.CLOSED, InflationMode.RADIAL,
        SolverMode.GEOMETRIC,
        (("inflation_amount", 0.2), ("minimum_amount", 0.0), ("sagginess", 0.035),
         ("sag_limit", 0.35), ("shape_retention", 0.25), ("volume_retention", 0.9),
         ("surface_slack", 0.0), ("iterations", 20), ("constraint_passes", 1)),
        (),
    ),
    TissuePreset.RIM: PresetValues(
        BaseDomain.CURVE, BoundaryMode.HOST_SEALED, InflationMode.PROFILE,
        SolverMode.GEOMETRIC,
        (("base_resolution", 33), ("inflation_amount", 0.12), ("profile_width", 0.08), ("profile_power", 0.65),
         ("profile_segments", 11), ("endpoint_taper", 0.12), ("sagginess", 0.08),
         ("sag_limit", 0.024), ("shape_retention", 0.72), ("volume_retention", 0.92),
         ("surface_slack", 0.0)),
        (("BACKING", "FIXED", 1.0), ("ENDPOINTS", "FIXED", 1.0)),
    ),
    TissuePreset.LAYER: PresetValues(
        BaseDomain.SURFACE, BoundaryMode.HOST_SEALED, InflationMode.NORMAL,
        SolverMode.GEOMETRIC,
        (("inflation_amount", 0.28), ("minimum_amount", 0.008), ("field_power", 0.78),
         ("sagginess", 0.65), ("sag_limit", 0.2), ("shape_retention", 0.48),
         ("volume_retention", 0.88), ("surface_slack", 0.0),
         ("iterations", 100), ("constraint_passes", 4)),
        (("BOUNDARY", "FIXED", 1.0), ("BACKING", "SOFT", 0.55)),
    ),
    TissuePreset.POUCH: PresetValues(
        BaseDomain.SURFACE, BoundaryMode.HOST_SEALED, InflationMode.NORMAL,
        SolverMode.STATIC_PBD,
        (("inflation_amount", 0.62), ("minimum_amount", 0.012), ("field_power", 0.58),
         ("sagginess", 0.58), ("sag_limit", 0.0), ("shape_retention", 0.48),
         ("volume_retention", 0.88), ("surface_slack", 0.0),
         ("iterations", 110), ("constraint_passes", 4)),
        (("BOUNDARY", "FIXED", 1.0), ("BACKING", "FIXED", 1.0)),
    ),
}
