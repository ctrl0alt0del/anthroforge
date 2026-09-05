"""Explicit category actions and a read-only summary of active-layer object hiding."""


def draw_category_visibility(layout, muscle_visibility, fiber_visibility):
    _draw_category(layout, "MUSCLE", "Muscles", muscle_visibility)
    _draw_category(layout, "FIBER", "Fibers", fiber_visibility)


def _draw_category(layout, category, label, summary):
    row = layout.row(align=True)
    row.label(text=label)
    actions = row.row(align=True)
    actions.enabled = bool(summary.available)
    _draw_action(actions, category, False, "Show", "HIDE_OFF")
    _draw_action(actions, category, True, "Hide", "HIDE_ON")
    text = summary.status
    if summary.unavailable:
        text += f" ({summary.unavailable} unavailable)"
    row.label(text=text)


def _draw_action(layout, category, hidden, label, icon):
    op = layout.operator("af.set_vcp_category_visibility", text=label, icon=icon)
    op.category, op.hidden = category, hidden
