"""Map resolved DSL volume to editable native inflation controls."""
from ...core.authoring.native_geometry import rebuild
from ...core.authoring.errors import require
from ...core.vcp.runtime_state import set_muscle_inflation_ctrl_world


def configure(muscle, output):
    native = output if 'native_properties' in output else rebuild(output, output['config'])
    muscle.pop('af_authoring_material', None)
    for key, value in native['native_properties'].items():
        if isinstance(value, (str, bool)):
            setattr(muscle, key, value)
        else:
            assign_checked(muscle, key, value)
    if muscle.inflation_mode == 'CTRL_POINT':
        set_muscle_inflation_ctrl_world(muscle, tuple(native['native_control_world']))


def assign_checked(item, key, value):
    setattr(item, key, value)
    require(abs(getattr(item, key)-value) <= max(1e-7, abs(value)*1e-6), "NATIVE_PARAMETER_RANGE", key)
