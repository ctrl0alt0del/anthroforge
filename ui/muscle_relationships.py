"""Relationship controls share production service and revision guards."""
import bpy
from ..core.utils import get_af_root
from ..core.muscle_pairs import runtime
from ..core.muscle_relationships import service
from ..adapters import relationship_region_editor as editor


def items(owner, context):
    root = get_af_root(context.scene) if context else None
    if root is None: return []
    state = runtime.inspect(context.scene, root); names = {m.id: m.name for m in root.af_vcp_system.muscles}
    rows = [enum_item(r, names) for r in state['relationships']]
    ITEMS[:] = rows
    return ITEMS


ITEMS = []
STRINGS = {}
NUMBERS = {}


def enum_item(row, names):
    identity = row['id']; number = NUMBERS.setdefault(identity, len(NUMBERS) + 1)
    label = ' / '.join(names.get(k[0], k[0]) + ' ' + k[1] + ' ' + k[2] for k in row['pair'])
    texts = [STRINGS.setdefault(v, v) for v in (identity, label, row['state'])]
    return (*texts, 0, number)


def selected(context, state):
    value = context.window_manager.af_relationship_selection
    return next((r for r in state['relationships'] if r['id'] == value), None)


def draw(layout, context, root, state):
    layout.label(text=f"Relationships · revision {state['relationship_revision']}")
    if state.get('relationship_error'): layout.label(text=state['relationship_error'], icon='ERROR'); recovery(layout); return
    if 'af_experiment_relationships_v1' in root: actions(layout, [('MIGRATE', 'Import experimental records')])
    if any('IDENTITY_CONFLICT' in i.get('message', '') for i in state['issues']): recovery(layout)
    layout.operator('af.muscle_explicit_order', text='Assign muscle pair…')
    if not state['relationships']: return
    layout.prop(context.window_manager, 'af_relationship_selection', text='Relationship')
    row = selected(context, state)
    if row is None: return
    layout.label(text=row['state'].replace('_', ' ').title() + ('' if row['current'] else ' · not current'))
    layout.label(text='Geometry: ' + row['status'].replace('_', ' '))
    controls(layout, row)
    draft_controls(layout, root, state)
    layout.label(text='Smoothing may extend beyond selected faces.')


def draft_controls(layout, root, state):
    draft = editor.SESSIONS.get(root.session_uid)
    if draft is None: return
    if (draft.revision, draft.result_revision) != (state['relationship_revision'], state['result_revision']):
        layout.label(text='Selection is stale; cancel and reopen.', icon='ERROR')
    actions(layout, [('APPLY', 'Apply selection'), ('CANCEL', 'Cancel')])


def actions(layout, values):
    line = layout.row()
    for action, label in values: line.operator('af.muscle_relationship_action', text=label).action = action


def controls(layout, row):
    intent = row['intent']
    actions(layout, [('EXCLUDE', 'Include' if intent.get('excluded') else 'Exclude'), ('AUTO', 'Automatic order')])
    actions(layout, [('FIRST', 'Request first as cover'), ('SECOND', 'Request second as cover')])
    actions(layout, [('ASSIGN_FIRST', 'Assign first as cover'), ('ASSIGN_SECOND', 'Assign second as cover')])
    actions(layout, [('EDIT', 'Edit support region'), ('CLEAR', 'Clear region')])
    if intent.get('cover'): layout.label(text=intent.get('mode', 'requested').title() + ' cover: ' + intent['cover'][0])
    if intent.get('region'): layout.label(text=f"Selected source faces: {len(intent['region']['faces'])}")
    if row.get('policy', {}).get('diagnostic'): layout.label(text=row['policy']['diagnostic'], icon='ERROR')


def recovery(layout):
    actions(layout, [('REKEY', 'Rekey this root'), ('MIGRATE', 'Import experimental records')])


def perform(context, action):
    from ..core.muscle_relationships import blender_identity, migration
    root = get_af_root(context.scene); scope = (context.scene, root); state = runtime.inspect(*scope)
    if action == 'REKEY': blender_identity.rekey(root); runtime.refresh(*scope, explicit=True); return
    if action == 'MIGRATE': migration.explicit_experiment(root); runtime.refresh(*scope, explicit=True); return
    if action == 'APPLY': editor.apply(root); return
    if action == 'CANCEL': editor.cancel(root); return
    row = selected(context, state)
    if row is None: raise ValueError('RELATIONSHIP_NOT_FOUND')
    if action == 'EDIT': editor.begin(root, context.scene, row['id']); return
    value = mutation_value(row, action)
    service.configure(scope, dict(relationships=[dict(id=row['id'], **value)]), state['relationship_revision'])


def mutation_value(row, action):
    return {'EXCLUDE': dict(excluded=not row['intent'].get('excluded', False)), 'AUTO': dict(cover=None, mode='automatic'),
        'FIRST': dict(cover=row['pair'][0], mode='requested'), 'SECOND': dict(cover=row['pair'][1], mode='requested'),
        'ASSIGN_FIRST': dict(cover=row['pair'][0], mode='explicit'), 'ASSIGN_SECOND': dict(cover=row['pair'][1], mode='explicit'),
        'CLEAR': dict(region=None)}[action]


class AF_OT_relationship_action(bpy.types.Operator):
    bl_idname = 'af.muscle_relationship_action'
    bl_label = 'Configure muscle relationship'
    bl_options = {'UNDO'}
    action: bpy.props.StringProperty()

    def execute(self, context):
        try: perform(context, self.action)
        except (ValueError, KeyError, RuntimeError) as error: self.report({'ERROR'}, str(error)); return {'CANCELLED'}
        return {'FINISHED'}


def register():
    from ..adapters import relationship_lifecycle
    from . import muscle_explicit_order
    muscle_explicit_order.register()
    bpy.utils.register_class(AF_OT_relationship_action)
    bpy.types.WindowManager.af_relationship_selection = bpy.props.EnumProperty(items=items, options={'SKIP_SAVE'})
    relationship_lifecycle.register()


def unregister():
    from ..adapters import relationship_lifecycle
    from . import muscle_explicit_order
    muscle_explicit_order.unregister()
    relationship_lifecycle.unregister()
    if hasattr(bpy.types.WindowManager, 'af_relationship_selection'): del bpy.types.WindowManager.af_relationship_selection
    bpy.utils.unregister_class(AF_OT_relationship_action)
    ITEMS.clear(); STRINGS.clear(); NUMBERS.clear()
