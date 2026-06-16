_PARENT_ITEMS = (
    ("KEEP", "Keep", "Use the authored parent anchor mode"),
    ("SURFACE_NEAREST", "Surface Nearest", "Temporarily anchor against the nearest point on the parent surface"),
    ("OBJECT_ORIGIN", "Object Origin", "Temporarily anchor against the parent object origin"),
)
_CHILD_ITEMS = (
    ("KEEP", "Keep", "Use the authored child anchor mode"),
    ("FACE_CENTER", "Face Center", "Temporarily use the nearest child face center"),
    ("VERTEX_NEAREST", "Nearest Vertex", "Temporarily use the nearest child mesh vertex"),
    ("OBJECT_ORIGIN", "Object Origin", "Temporarily use the child object origin"),
)
_FOLLOW_ITEMS = (
    ("KEEP", "Keep", "Use the authored Follow Rotation value"),
    ("ENABLED", "Enabled", "Temporarily enable Follow Rotation"),
    ("DISABLED", "Disabled", "Temporarily disable Follow Rotation"),
)
_STRATEGY_ITEMS = (
    ("KEEP", "Keep", "Use the authored rotation strategy"),
    ("AUTO", "Auto", "Use deformation flow when the parent exposes a flow direction"),
    ("STABLE_SURFACE", "Stable Surface", "Keep rotation stable against triangle drift"),
    ("DEFORMATION_FLOW", "Deformation Flow", "Follow the stored parent surface flow"),
)
_PARENT_MODES = {item[0] for item in _PARENT_ITEMS}
_CHILD_MODES = {item[0] for item in _CHILD_ITEMS}
_FOLLOW_MODES = {item[0] for item in _FOLLOW_ITEMS}
_STRATEGY_MODES = {item[0] for item in _STRATEGY_ITEMS}


def parent_override_items():
    return _PARENT_ITEMS


def child_override_items():
    return _CHILD_ITEMS


def follow_rotation_override_items():
    return _FOLLOW_ITEMS


def rotation_strategy_override_items():
    return _STRATEGY_ITEMS


def override_entry(shortcut, target_scp_id):
    tid = str(target_scp_id or "")
    return next((item for item in getattr(shortcut, "overrides", ()) if str(getattr(item, "target_scp_id", "")) == tid), None)


def override_modes(shortcut, target_scp_id):
    return override_values(shortcut, target_scp_id)[:2]


def override_values(shortcut, target_scp_id):
    entry = override_entry(shortcut, target_scp_id)
    return (
        _entry_mode(entry, "parent_anchor_mode", _PARENT_MODES),
        _entry_mode(entry, "child_anchor_mode", _CHILD_MODES),
        _entry_mode(entry, "follow_rotation_mode", _FOLLOW_MODES),
        _entry_mode(entry, "rotation_strategy", _STRATEGY_MODES),
    )


def _entry_mode(entry, key, valid):
    return _normalized("KEEP" if entry is None else getattr(entry, key, "KEEP"), valid)


def has_override(shortcut, target_scp_id):
    return any(value != "KEEP" for value in override_values(shortcut, target_scp_id))


def clear_override(shortcut, target_scp_id):
    tid = str(target_scp_id or "")
    for index, entry in enumerate(getattr(shortcut, "overrides", ())):
        if str(getattr(entry, "target_scp_id", "")) == tid:
            shortcut.overrides.remove(index)
            return True
    return False


def upsert_override(shortcut, target_scp_id, parent_mode, child_mode, follow_rotation_mode="KEEP", rotation_strategy="KEEP"):
    values = _override_payload(parent_mode, child_mode, follow_rotation_mode, rotation_strategy)
    if all(value == "KEEP" for value in values):
        return clear_override(shortcut, target_scp_id)
    entry = override_entry(shortcut, target_scp_id) or shortcut.overrides.add()
    entry.target_scp_id = str(target_scp_id or "")
    entry.parent_anchor_mode, entry.child_anchor_mode = values[:2]
    entry.follow_rotation_mode, entry.rotation_strategy = values[2:]
    return True


def remap_overrides(dst_shortcut, src_shortcut, scp_map):
    for item in getattr(src_shortcut, "overrides", ()):
        mapped = str(dict(scp_map or {}).get(str(getattr(item, "target_scp_id", "")), "") or "")
        if mapped:
            upsert_override(dst_shortcut, mapped, getattr(item, "parent_anchor_mode", "KEEP"), getattr(item, "child_anchor_mode", "KEEP"), getattr(item, "follow_rotation_mode", "KEEP"), getattr(item, "rotation_strategy", "KEEP"))


def _normalized(value, valid):
    mode = str(value or "KEEP").upper()
    return mode if mode in valid else "KEEP"


def _override_payload(parent_mode, child_mode, follow_mode, strategy):
    return (
        _normalized(parent_mode, _PARENT_MODES),
        _normalized(child_mode, _CHILD_MODES),
        _normalized(follow_mode, _FOLLOW_MODES),
        _normalized(strategy, _STRATEGY_MODES),
    )
