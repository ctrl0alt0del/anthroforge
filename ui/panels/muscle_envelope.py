"""Both-side controls; editing selection never hides scene geometry."""
from ...core.visualization.muscle_envelope_storage import selected_settings
from ...core.visualization.branch_control import branch_surface


def draw(layout, root, muscle):
    layout.prop(muscle, 'envelope_sides', expand=True)
    if muscle.envelope_sides != 'BOTH_SIDES': return _one_side(layout, muscle)
    box = layout.box(); box.prop(muscle, 'envelope_enabled')
    box.prop(muscle, 'envelope_edit_side', expand=True)
    settings, branch, _ = selected_settings(root, muscle)
    box.label(text=f"Side {muscle.envelope_edit_side} / {branch or 'Main'}: depth from base")
    _settings(box, settings, muscle, branch_surface(root, muscle) is not None)
    _actions(box, muscle)
    _diagnostics(box, muscle)
    return True


def _action(layout, muscle, action, label):
    op = layout.operator('af.muscle_envelope_action', text=label)
    op.muscle_id, op.action = muscle.id, action


def _settings(layout, settings, muscle, branch):
    layout.prop(settings, 'inflation_enabled', text='Side Enabled')
    _modes(layout, settings, muscle, branch)
    if settings.inflation_mode == 'SECTION_PROFILE':
        if branch: layout.label(text='Section Profile requires an ordinary open loft', icon='ERROR'); return
        return _profile(layout, settings, muscle)
    for name in ('inflation_max_value', 'inflation_boundary_strength', 'inflation_boundary_band', 'inflation_boundary_power'):
        layout.prop(settings, name)
    if settings.inflation_mode == 'CTRL_POINT':
        for name in ('inflation_falloff_type', 'inflation_falloff_radius', 'inflation_direction_depth', 'inflation_ctrl_world'):
            layout.prop(settings, name)
        op = layout.operator('af.select_muscle_inflation_ctrl', text='Select Side Control'); op.muscle_id = muscle.id
    else: layout.prop(settings, 'inflation_length_taper_band')


def _profile(layout, settings, muscle):
    if settings.section_profile_version != 1:
        _action(layout, muscle, 'INITIALIZE_PROFILE', 'Initialize Section Profile'); return
    layout.prop(settings, 'section_direction')
    for index in range(4):
        row = layout.row(align=True); row.label(text=f'{(index+1)*20}%')
        row.prop(settings, 'section_depths', index=index, text='Depth'); row.prop(settings, 'section_peaks', index=index, text='Peak')
    layout.prop(settings, 'section_roundness')
    row = layout.row(align=True)
    _action(row, muscle, 'SCALE_PROFILE', 'Scale Depths')
    _action(row, muscle, 'RESET_PROFILE', 'Reset Depths')


def _modes(layout, settings, muscle, branch):
    for mode, label in (('CTRL_POINT', 'Control Point'), ('DISTRIBUTED', 'Distributed'), ('SECTION_PROFILE', 'Section Profile')):
        row = layout.row(); row.enabled = not (branch and mode == 'SECTION_PROFILE')
        op = row.operator('af.muscle_envelope_mode', text=label, depress=settings.inflation_mode == mode)
        op.muscle_id, op.mode = muscle.id, mode


def _actions(layout, muscle):
    row = layout.row(align=True)
    for action, label in (('COPY_A_B', 'Copy A to B'), ('COPY_B_A', 'Copy B to A')): _action(row, muscle, action, label)
    row = layout.row(align=True)
    for action, label in (('COPY_ALL_A_B', 'All Parts A to B'), ('COPY_ALL_B_A', 'All Parts B to A')): _action(row, muscle, action, label)
    _action(layout, muscle, 'REVERSE', 'Reverse Inflation Sides')


def _diagnostics(layout, muscle):
    import json
    error = muscle.get('_af_rt_section_profile_error', '')
    if error: layout.label(text=error, icon='ERROR')
    report = json.loads(muscle.get('_af_rt_envelope_diagnostics', '{}'))
    for warning in report.get('warnings', []): layout.label(text=warning.replace('_', ' '), icon='ERROR')


def _one_side(layout, muscle):
    if muscle.envelope_version:
        layout.prop(muscle, 'envelope_enabled', text='Envelope Enabled')
        layout.prop(muscle, 'envelope_reverse')
    return False
