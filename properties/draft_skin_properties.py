import bpy

from ..core.draft_skin.settings import root_settings_percentages


_DEFAULTS = root_settings_percentages()


class AF_DraftSkinSettings_Property(bpy.types.PropertyGroup):
    minimum_offset_percent: bpy.props.FloatProperty(
        name="Minimum Skin Distance", description="Required envelope distance as a percentage of model length",
        default=_DEFAULTS["minimum_offset_percent"], min=0.0, max=2.0, precision=4,
    )
    collagen_depth_percent: bpy.props.FloatProperty(
        name="Maximum Collagen Depth", description="Additional full-collagen depth as a percentage of model length",
        default=_DEFAULTS["collagen_depth_percent"], min=0.0, max=4.0, precision=4,
    )
    collagen_core_percent: bpy.props.FloatProperty(
        name="Collagen Core Radius", description="Radius retaining the painted value as a percentage of model length",
        default=_DEFAULTS["collagen_core_percent"], min=0.0, max=5.0, precision=4,
    )
    collagen_falloff_percent: bpy.props.FloatProperty(
        name="Collagen Falloff Width", description="Smooth transition width as a percentage of model length",
        default=_DEFAULTS["collagen_falloff_percent"], min=0.0, max=10.0, precision=4,
    )
