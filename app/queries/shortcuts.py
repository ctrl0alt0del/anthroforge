from dataclasses import dataclass, field

try:
    from ...core.shortcuts import resolve_shortcut
    from ...core.shortcuts.owners import current_shortcut_owner, matches_shortcut_owner
except ImportError:
    from core.shortcuts import resolve_shortcut
    from core.shortcuts.owners import current_shortcut_owner, matches_shortcut_owner

from .root import root_for_context, scene_from_context


@dataclass(frozen=True)
class ShortcutRowState:
    shortcut: object = None
    target: object = None


@dataclass(frozen=True)
class ShortcutPanelState:
    scene: object = None
    root: object = None
    rows: tuple = field(default_factory=tuple)


def visible_shortcuts(root, context):
    items = tuple(root.af_shortcut_system.shortcuts)
    if getattr(context.scene, "af_shortcut_view_mode", "SELECTED") == "ALL":
        return items
    kind, owner_id = current_shortcut_owner(root, context)
    return [item for item in items if matches_shortcut_owner(item, kind, owner_id)]


def _row_state(root, context, shortcut):
    return ShortcutRowState(shortcut=shortcut, target=resolve_shortcut(root, context, shortcut.data_path))


def shortcut_panel_state(context):
    scene = scene_from_context(context)
    root = root_for_context(context)
    if root is None:
        return ShortcutPanelState(scene=scene)
    rows = tuple(_row_state(root, context, item) for item in visible_shortcuts(root, context))
    return ShortcutPanelState(scene=scene, root=root, rows=rows)
