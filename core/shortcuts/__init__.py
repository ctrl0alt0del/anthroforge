from .path_codec import normalize_shortcut_path, parse_shortcut_path
from .resolver import ShortcutTarget, resolve_shortcut

__all__ = [
    "ShortcutTarget",
    "normalize_shortcut_path",
    "parse_shortcut_path",
    "resolve_shortcut",
]
