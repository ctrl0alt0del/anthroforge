"""Optional height smoothing; RNA callbacks only request canonical rebuilding."""
import bpy


def updated(settings, context):
    from ..core.vcp.prop_update_guard import vcp_prop_updates_suppressed
    from ..core.visualization.muscle_envelope_storage import owner_for, initialize
    from .muscle_envelope import updated as refresh
    if vcp_prop_updates_suppressed(): return
    owner = owner_for(settings.id_data, settings)
    if owner is not None: initialize(owner)
    refresh(settings, context)


def install(muscle_type):
    muscle_type.__annotations__.update(inflation_smoothing_mode=bpy.props.EnumProperty(
        name='Height Smoothing', default='OFF', items=(('OFF', 'Off', 'Keep existing inflation unchanged'),
        ('HEIGHT', 'Height', 'Smooth inflation height with fixed borders and creases')), update=updated))
    for key, label, default, description in (
        ('radius', 'Smoothing Radius', .2, 'World-space smoothing length; larger values affect broader features'),
        ('strength', 'Smoothing Strength', .8, 'Curvature penalty relative to the existing inflation height'),
        ('max_change', 'Maximum Height Change', .05, 'Maximum world-space change from the original inflation')):
        muscle_type.__annotations__['inflation_smoothing_'+key] = bpy.props.FloatProperty(
            name=label, default=default, min=0, max=1000, description=description, update=updated)
