"""Undoable envelope actions using the same candidate evaluator as authoring."""
import bpy
from .muscle_profile import _muscle
from ..app.use_cases import muscle_envelope as commands
from ..core.authoring.envelope_config import configuration, side_state
from ..core.visualization.muscle_envelope_storage import selected_settings
from ..core.vcp.muscle_section_profile import reset_profile, profile_properties
from ..core.vcp.prop_update_guard import suppress_vcp_prop_updates


class AF_OT_MuscleEnvelopeAction(bpy.types.Operator):
    bl_idname = 'af.muscle_envelope_action'
    bl_label = 'Configure Muscle Inflation'
    bl_options = {'REGISTER', 'UNDO'}
    muscle_id: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=tuple((v, v.replace('_', ' ').title(), '') for v in
        ('COPY_A_B', 'COPY_B_A', 'COPY_ALL_A_B', 'COPY_ALL_B_A', 'REVERSE', 'INITIALIZE_PROFILE', 'SCALE_PROFILE', 'RESET_PROFILE')))

    factor: bpy.props.FloatProperty(name='Depth Scale', default=1.0, min=0.0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self) if self.action == 'SCALE_PROFILE' else self.execute(context)

    def draw(self, context):
        self.layout.prop(self, 'factor')

    def execute(self, context):
        try:
            root, muscle = _muscle(context, self.muscle_id)
            with commands.transaction(root, context.scene, muscle):
                config = action_configuration(root, muscle, self.action, self.factor)
                if self.action.startswith('COPY'): commands.copy_banks(root, muscle, self.action)
                commands.configure(root, context.scene, muscle.id, config)
            return {'FINISHED'}
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


def action_configuration(root, muscle, action, factor=1.):
    config = configuration(root, muscle); settings, key, _ = selected_settings(root, muscle)
    if action == 'REVERSE': config['reverse_sides'] = not config['reverse_sides']
    elif action in ('INITIALIZE_PROFILE', 'RESET_PROFILE', 'SCALE_PROFILE'):
        row = next(p for p in config['parts'] if p['part_id'] == (key or 'main'))
        row[muscle.envelope_edit_side.lower()] = _profile_action(settings, action, factor)
    else:
        source, destination = ('a', 'b') if action.endswith('A_B') else ('b', 'a')
        for row in config['parts']:
            if 'ALL' in action or row['part_id'] == (key or 'main'): row[destination] = row[source]
    return config


def _profile_action(settings, action, factor):
    from ..core.authoring.profile_config import wire
    from ..core.vcp.muscle_section_profile import profile_from_muscle, scale_profile
    spec = scale_profile(profile_from_muscle(settings), factor) if action == 'SCALE_PROFILE' else reset_profile(settings.inflation_max_value)
    profile = wire(spec); profile.pop('flip_normals')
    mode, enabled = profile.pop('mode'), profile.pop('enabled')
    return dict(mode=mode, enabled=enabled, parameters=profile)


class AF_OT_MuscleEnvelopeMode(bpy.types.Operator):
    bl_idname = 'af.muscle_envelope_mode'
    bl_label = 'Set Inflation Side Mode'
    bl_options = {'REGISTER', 'UNDO'}
    muscle_id: bpy.props.StringProperty()
    mode: bpy.props.EnumProperty(items=tuple((x, x, '') for x in ('CTRL_POINT', 'DISTRIBUTED', 'SECTION_PROFILE')))

    def execute(self, context):
        try:
            root, muscle = _muscle(context, self.muscle_id)
            settings, _, _ = selected_settings(root, muscle)
            from ..core.visualization.branch_control import branch_surface
            if self.mode == 'SECTION_PROFILE' and branch_surface(root, muscle): raise ValueError('PROFILE_DOMAIN_UNSUPPORTED')
            with commands.transaction(root, context.scene, muscle):
                settings.inflation_mode = self.mode
                commands.configure(root, context.scene, muscle.id, configuration(root, muscle))
            return {'FINISHED'}
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, str(error)); return {'CANCELLED'}


CLASSES = (AF_OT_MuscleEnvelopeAction, AF_OT_MuscleEnvelopeMode,)
