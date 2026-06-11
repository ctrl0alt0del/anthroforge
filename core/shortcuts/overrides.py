def _keep_mode(value):
    mode = str(value or "KEEP").upper()
    return mode if mode else "KEEP"


def parent_override_items():
    return (
        ("KEEP", "Keep", "Use the authored parent anchor mode"),
        ("SURFACE_NEAREST", "Surface Nearest", "Temporarily anchor against the nearest point on the parent surface"),
        ("OBJECT_ORIGIN", "Object Origin", "Temporarily anchor against the parent object origin"),
    )


def child_override_items():
    return (
        ("KEEP", "Keep", "Use the authored child anchor mode"),
        ("FACE_CENTER", "Face Center", "Temporarily use the nearest child face center"),
        ("VERTEX_NEAREST", "Nearest Vertex", "Temporarily use the nearest child mesh vertex"),
        ("OBJECT_ORIGIN", "Object Origin", "Temporarily use the child object origin"),
    )


def override_entry(shortcut, target_scp_id):
    tid = str(target_scp_id or "")
    return next((item for item in getattr(shortcut, "overrides", ()) if str(getattr(item, "target_scp_id", "")) == tid), None)


def override_modes(shortcut, target_scp_id):
    entry = override_entry(shortcut, target_scp_id)
    return (_entry_mode(entry, "parent_anchor_mode"), _entry_mode(entry, "child_anchor_mode"))


def _entry_mode(entry, key):
    return "KEEP" if entry is None else _keep_mode(getattr(entry, key, "KEEP"))


def has_override(shortcut, target_scp_id):
    parent_mode, child_mode = override_modes(shortcut, target_scp_id)
    return parent_mode != "KEEP" or child_mode != "KEEP"


def clear_override(shortcut, target_scp_id):
    tid = str(target_scp_id or "")
    for index, entry in enumerate(getattr(shortcut, "overrides", ())):
        if str(getattr(entry, "target_scp_id", "")) == tid:
            shortcut.overrides.remove(index)
            return True
    return False


def upsert_override(shortcut, target_scp_id, parent_mode, child_mode):
    if _keep_mode(parent_mode) == "KEEP" and _keep_mode(child_mode) == "KEEP":
        return clear_override(shortcut, target_scp_id)
    entry = override_entry(shortcut, target_scp_id) or shortcut.overrides.add()
    entry.target_scp_id = str(target_scp_id or "")
    entry.parent_anchor_mode = _keep_mode(parent_mode)
    entry.child_anchor_mode = _keep_mode(child_mode)
    return True


def remap_overrides(dst_shortcut, src_shortcut, scp_map):
    for item in getattr(src_shortcut, "overrides", ()):
        mapped = str(dict(scp_map or {}).get(str(getattr(item, "target_scp_id", "")), "") or "")
        if mapped:
            upsert_override(dst_shortcut, mapped, getattr(item, "parent_anchor_mode", "KEEP"), getattr(item, "child_anchor_mode", "KEEP"))
