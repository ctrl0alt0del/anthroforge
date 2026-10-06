"""Side/part-local scalar smoothing controls."""


def draw(layout, settings):
    box = layout.box()
    box.prop(settings, 'inflation_smoothing_mode')
    if settings.inflation_smoothing_mode != 'HEIGHT': return
    for key in ('radius', 'strength', 'max_change'):
        box.prop(settings, 'inflation_smoothing_'+key)
    box.label(text='Borders and existing zero-depth creases stay fixed')
    error = settings.get('_af_rt_section_profile_error', '')
    if error.startswith('SMOOTHING_'): box.label(text=error, icon='ERROR')
