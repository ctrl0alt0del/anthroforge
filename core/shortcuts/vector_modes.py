def shortcut_vector_mode(shortcut):
    mode = str(getattr(shortcut, "vector_mode", "DEFAULT") or "DEFAULT").upper()
    return mode if mode in {"DEFAULT", "UNIFORM"} else "DEFAULT"


def is_uniform_vector_shortcut(shortcut, target=None):
    return shortcut_vector_mode(shortcut) == "UNIFORM" and _uniform_target(target)


def _uniform_target(target):
    if target is None:
        return True
    kind = str(getattr(target, "value_type", "") or "").upper()
    size = int(getattr(target, "array_length", 0) or 0)
    return size > 1 and int(getattr(target, "index", -1)) < 0 and kind in {"INT", "FLOAT"}
