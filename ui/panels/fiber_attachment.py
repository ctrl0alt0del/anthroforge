"""Shared surface bindings and explicit additional support selection."""
from ...app.queries.scp import scp_label
from ...core.vcp.shared_point_storage import slots, point_record


def draw(layout, root, fiber):
    box = layout.box(); box.label(text='Surface Attachments')
    box.label(text='Choose a surface; place the cursor at its attachment.')
    for owner, slot, role in slots(fiber):
        point = point_record(owner, slot)
        if point is not None: _point(box, root, point, role)
    _supports(box, root, fiber)
    op = box.operator('af.fiber_attachment', text='Rebind All at Retained Positions')
    op.action, op.fiber_id = 'REBIND_ALL', fiber.id
    box.operator('af.fiber_attachment_symmetry', text='Symmetry Settings').fiber_id = fiber.id


def _point(box, root, point, role):
    box.label(text=f'{role.title()}: {scp_label(root, point.parent_id)}')
    row = box.row(align=True)
    for action, label in (('ASSIGN', 'Assign Surface…'), ('REBIND', 'Rebind at Cursor'), ('SELECT', 'Select Parent')):
        op = row.operator('af.fiber_attachment', text=label)
        op.action, op.point_id, op.target_id = action, point.id, point.parent_id


def _supports(box, root, fiber):
    box.label(text='Additional Supports')
    op = box.operator('af.fiber_attachment', text='Add Support…', icon='ADD')
    op.action, op.fiber_id = 'ADD', fiber.id
    for item in fiber.attachment_supports:
        row = box.row(align=True); row.label(text=scp_label(root, item.target_id))
        for action, icon in (('SELECT', 'RESTRICT_SELECT_OFF'), ('REMOVE', 'X')):
            op = row.operator('af.fiber_attachment', text='', icon=icon)
            op.action, op.fiber_id, op.target_id = action, fiber.id, item.target_id
