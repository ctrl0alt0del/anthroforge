"""RNA envelope settings and callbacks; numerical work stays outside RNA."""
import bpy
from ..core.vcp.prop_update_guard import vcp_prop_updates_suppressed


def updated(settings, context):
    if vcp_prop_updates_suppressed(): return
    from ..core.visualization.muscle_envelope_storage import owner_for, initialize
    from ..core.visualization.muscle_profile_publish import refresh
    muscle = owner_for(settings.id_data, settings)
    if muscle is None: return
    if muscle.envelope_sides == 'BOTH_SIDES':
        initialize(muscle)
        initialize_profile(settings)
    refresh(muscle.id_data, context.scene, muscle.id)


def control_updated(settings, context):
    if vcp_prop_updates_suppressed(): return
    settings.inflation_ctrl_initialized = True
    updated(settings, context)


class AF_MuscleSideProperties(bpy.types.PropertyGroup):
    id: bpy.props.StringProperty()
    initialized: bpy.props.BoolProperty(default=False)
    closed_v: bpy.props.BoolProperty(default=False)
    flip_normals: bpy.props.BoolProperty(default=False)


def install(muscle_type):
    for key, prop in muscle_type.__annotations__.items():
        if key.startswith(('inflation_', 'section_')):
            callback = control_updated if key == 'inflation_ctrl_world' else updated
            AF_MuscleSideProperties.__annotations__[key] = prop.function(**dict(prop.keywords, update=callback))
    muscle_type.__annotations__.update(_envelope_fields())


def _envelope_fields():
    return dict(inflation_secondary=bpy.props.PointerProperty(type=AF_MuscleSideProperties),
        envelope_version=bpy.props.IntProperty(default=0),
        envelope_sides=bpy.props.EnumProperty(name='Sides', default='ONE_SIDE', update=updated,
            items=(('ONE_SIDE', 'One Side', ''), ('BOTH_SIDES', 'Both Sides', 'Adds inflation opposite the base; existing side stays unchanged'))),
        envelope_enabled=bpy.props.BoolProperty(name='Inflation Enabled', default=True, update=updated),
        envelope_reverse=bpy.props.BoolProperty(name='Reverse Inflation Sides', default=False, update=updated),
        envelope_edit_side=bpy.props.EnumProperty(name='Edit Side', default='A', update=updated,
            items=(('A', 'A', 'Original material side'), ('B', 'B', 'Opposite material side'))))


def initialize_profile(settings):
    from ..core.vcp.prop_update_guard import suppress_vcp_prop_updates
    from ..core.vcp.muscle_section_profile import reset_profile, profile_properties
    if settings.inflation_mode == 'SECTION_PROFILE' and settings.section_profile_version == 0:
        with suppress_vcp_prop_updates():
            for key, value in profile_properties(reset_profile(settings.inflation_max_value)).items(): setattr(settings, key, value)
