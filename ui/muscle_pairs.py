"""Compact geometry-only candidate inspector over the shared detection service."""
import bpy
from ..core.utils import get_af_root
from ..core.muscle_pairs import configuration, runtime


def set_value(owner, name, value):
    with configuration.transaction(owner.id_data, {name: value}): pass
    for scene in bpy.data.scenes:
        if owner.id_data.name in scene.objects: runtime.refresh(scene, owner.id_data, explicit=name == 'stacking')


class AF_PairSettings(bpy.types.PropertyGroup):
    automatic: bpy.props.BoolProperty(name='Automatic refresh',
        get=lambda s: configuration.read(s.id_data)['automatic'], set=lambda s, v: set_value(s, 'automatic', v))
    search: bpy.props.FloatProperty(name='Search distance', min=0, precision=4,
        description='Search distance in current geometry units',
        get=lambda s: configuration.read(s.id_data)['search_distance'], set=lambda s, v: set_value(s, 'search_distance', v))
    displacement: bpy.props.FloatProperty(name='Maximum bonus / search allowance', min=0, precision=4,
        description='Additional displacement in current geometry units',
        get=lambda s: configuration.read(s.id_data)['displacement'], set=lambda s, v: set_value(s, 'displacement', v))
    stacking: bpy.props.BoolProperty(name='Auto Stacking',
        get=lambda s: configuration.read(s.id_data)['stacking'], set=lambda s, v: set_value(s, 'stacking', v))
    clearance: bpy.props.FloatProperty(name='Stack clearance', min=0, precision=4,
        get=lambda s: configuration.read(s.id_data)['clearance'], set=lambda s, v: set_value(s, 'clearance', v))
    radius: bpy.props.FloatProperty(name='Bonus smoothing radius', min=0, precision=4,
        get=lambda s: configuration.read(s.id_data)['smoothing_radius'], set=lambda s, v: set_value(s, 'smoothing_radius', v))
    strength: bpy.props.FloatProperty(name='Bonus smoothing strength', min=0,
        get=lambda s: configuration.read(s.id_data)['smoothing_strength'], set=lambda s, v: set_value(s, 'smoothing_strength', v))


class AF_OT_pair_refresh(bpy.types.Operator):
    bl_idname = 'af.muscle_pairs_refresh'
    bl_label = 'Refresh overlap candidates'

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None: return {'CANCELLED'}
        runtime.refresh(context.scene, root, explicit=True)
        return {'FINISHED'}


class AF_PT_muscle_pairs(bpy.types.Panel):
    bl_label = 'Muscle overlap candidates'
    bl_idname = 'AF_PT_muscle_pairs'
    bl_space_type, bl_region_type, bl_category = 'VIEW_3D', 'UI', 'AnthroForge'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        from .muscle_relationships import draw as draw_relationships
        root = get_af_root(context.scene); layout = self.layout; props = root.af_pair_settings
        row = layout.row(); row.prop(props, 'automatic'); row.operator('af.muscle_pairs_refresh', text='Refresh')
        layout.prop(props, 'search'); layout.prop(props, 'displacement')
        state = runtime.inspect(context.scene, root)
        layout.label(text=f"{state['status'].replace('_', ' ').title()} · {state['result_revision']}")
        draw_stacking(layout, props, state)
        draw_candidates(layout, context, root, state)
        draw_relationships(layout, context, root, state)


def draw_candidates(layout, context, root, state):
    pairs = [p for p in state['pairs'] if p['fragments'] or p['projection_warnings']]
    layout.label(text=f'{len(pairs)} overlap candidates')
    if pairs:
        layout.prop(context.window_manager, 'af_pair_selection', text='Candidate')
        selected = min(context.window_manager.af_pair_selection, len(pairs)-1)
        names = {m.id: m.name for m in root.af_vcp_system.muscles}
        for row in pairs[max(0, selected-2):selected+3]:
            a, b = row['first'], row['second']; box = layout.box()
            box.label(text=f"#{row['index']} {names.get(a['muscle'], a['muscle'])} {a['side']} / {names.get(b['muscle'], b['muscle'])} {b['side']}",
                      icon='RADIOBUT_ON' if row is pairs[selected] else 'RADIOBUT_OFF')
            box.label(text=f"{a['instance']} · {row['fragments']} fragments · {row['projection_warnings']} projection warnings")
        draw_order(layout, pairs[selected], state)
    for issue in state['issues'][:5]: layout.label(text=issue['message'][:100], icon='ERROR')


def draw_order(layout, pair, state):
    order = pair.get('order', {})
    layout.label(text='Order: '+order.get('status', 'pending').replace('_', ' '))
    if order.get('underlying'):
        layout.label(text=order['underlying']['muscle']+' → '+order['covering']['muscle'])
    for domain in state.get('stacking', {}).get('domains', ()):
        if domain['domain'] in (pair['first'], pair['second']): layout.label(text=domain['domain']['muscle']+': '+domain['status'])
    area = sum(order.get('positive_fragment_area', ()))
    layout.label(text=f'Positive fragment area sum: {area:.6g}')
    excluded = pair.get('policy', {}).get('status') == 'excluded' or order.get('status') == 'excluded'
    layout.operator('af.muscle_pair_exclude', text='Include pair' if excluded else 'Exclude pair')


def draw_stacking(layout, props, state):
    layout.prop(props, 'stacking')
    if props.stacking:
        layout.prop(props, 'clearance'); layout.prop(props, 'radius'); layout.prop(props, 'strength')
    stack = state.get('stacking', {})
    layout.label(text='Stacking: '+stack.get('status', 'not evaluated').replace('_', ' '))
    for domain in stack.get('domains', ()):
        if domain['diagnostics']: layout.label(text=domain['diagnostics'][:100], icon='ERROR')


def selected_pair(context, root, state):
    pairs = [p for p in state['pairs'] if p['fragments'] or p['projection_warnings']]
    return pairs[min(context.window_manager.af_pair_selection, len(pairs)-1)] if pairs else None


def exclusion_key(pair):
    return [[pair[k][name] for name in ('muscle', 'instance', 'side')] for k in ('first', 'second')]


class AF_OT_pair_exclude(bpy.types.Operator):
    bl_idname = 'af.muscle_pair_exclude'
    bl_label = 'Toggle selected pair exclusion'
    bl_options = {'UNDO'}

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None: return {'CANCELLED'}
        pair = selected_pair(context, root, runtime.inspect(context.scene, root))
        if pair is None: return {'CANCELLED'}
        key = exclusion_key(pair); values = configuration.read(root)['exclusions']
        prior = next((v for v in values if sorted(v) == sorted(key)), None)
        values = [v for v in values if v != prior] if prior else [*values, key]
        with configuration.transaction(root, dict(exclusions=values)): pass
        runtime.refresh(context.scene, root, explicit=True)
        return {'FINISHED'}


CLASSES = (AF_PairSettings, AF_OT_pair_refresh, AF_OT_pair_exclude, AF_PT_muscle_pairs)


def register():
    from . import muscle_relationships
    for cls in CLASSES: bpy.utils.register_class(cls)
    bpy.types.Object.af_pair_settings = bpy.props.PointerProperty(type=AF_PairSettings)
    bpy.types.WindowManager.af_pair_selection = bpy.props.IntProperty(default=0, min=0, options={'SKIP_SAVE'})
    muscle_relationships.register()
    runtime.register()


def unregister():
    from . import muscle_relationships
    runtime.unregister()
    muscle_relationships.unregister()
    for owner, name in ((bpy.types.Object, 'af_pair_settings'), (bpy.types.WindowManager, 'af_pair_selection')):
        if hasattr(owner, name): delattr(owner, name)
    for cls in reversed(CLASSES): bpy.utils.unregister_class(cls)
