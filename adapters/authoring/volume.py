"""Map resolved DSL volume to editable native inflation controls."""
from ...core.authoring.native_geometry import rebuild
from ...core.authoring.errors import require
from ...core.vcp.runtime_state import set_muscle_inflation_ctrl_world


def configure(muscle, output):
    native = output if 'native_properties' in output else rebuild(output, output['config'])
    muscle.pop('af_authoring_material', None)
    for key, value in sorted(native['native_properties'].items(), key=lambda row: row[0] == 'inflation_mode'):
        if isinstance(value, (str, bool)):
            setattr(muscle, key, value)
        else:
            assign_checked(muscle, key, value)
    if 'envelope_configuration' in output and 'branch_parts' not in output:
        from ...app.use_cases.muscle_envelope import write
        write(muscle.id_data, muscle, output['envelope_configuration'])
    if muscle.inflation_mode == 'CTRL_POINT' and 'envelope_configuration' not in output:
        set_muscle_inflation_ctrl_world(muscle, tuple(native['native_control_world']))


def assign_checked(item, key, value):
    from ...core.authoring.native_assignment import assign_checked as assign
    assign(item, key, value)
