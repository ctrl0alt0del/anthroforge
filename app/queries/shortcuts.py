from dataclasses import dataclass, field

try:
    from ...core.shortcuts import has_override, resolve_shortcut
    from ...core.shortcuts.owners import current_shortcut_owner, matches_shortcut_owner, selected_scp_id, shortcut_relation
except ImportError:
    from core.shortcuts import has_override, resolve_shortcut
    from core.shortcuts.owners import current_shortcut_owner, matches_shortcut_owner, selected_scp_id, shortcut_relation

from .root import root_for_context, scene_from_context


@dataclass(frozen=True)
class ShortcutRowState:
    shortcut: object = None
    target: object = None
    selected_scp_id: str = ""
    owner_relation: str = "UNRELATED"
    show_settings: bool = False
    has_settings: bool = False
    show_override: bool = False
    has_override: bool = False


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


def _row_state(root, context, shortcut, selected_id):
    relation = shortcut_relation(root, shortcut, selected_id)
    shown = _show_override(context, relation)
    return ShortcutRowState(shortcut=shortcut, target=resolve_shortcut(root, context, shortcut.data_path), selected_scp_id=selected_id, owner_relation=relation, show_settings=_show_settings(shortcut), has_settings=_has_settings(shortcut), show_override=shown, has_override=shown and has_override(shortcut, selected_id))


def _show_override(context, relation):
    return getattr(context.scene, "af_shortcut_view_mode", "SELECTED") == "ALL" and relation == "ANCESTOR"


def _show_settings(shortcut):
    return str(getattr(shortcut, "owner_type", "") or "") == "SCP"


def _has_settings(shortcut):
    return bool(getattr(shortcut, "overrides", ())) or not bool(getattr(shortcut, "owner_backsolve", True))


def shortcut_panel_state(context):
    scene = scene_from_context(context)
    root = root_for_context(context)
    if root is None:
        return ShortcutPanelState(scene=scene)
    sid = selected_scp_id(root, context)
    rows = tuple(_row_state(root, context, item, sid) for item in visible_shortcuts(root, context))
    return ShortcutPanelState(scene=scene, root=root, rows=rows)
