import json


def selection_order(scene):
    raw = "[]" if scene is None else str(getattr(scene, "af_selection_order_json", "[]") or "[]")
    try:
        data = json.loads(raw)
    except Exception:
        data = []
    return [str(v) for v in data if str(v or "")]


def set_selection_order(scene, names):
    if scene is not None:
        value = json.dumps([str(v) for v in tuple(names or ()) if str(v or "")])
        if getattr(scene, 'af_selection_order_json', '') != value: scene.af_selection_order_json = value


def _is_selected(obj):
    return bool(obj and getattr(obj, "select_get", None) and obj.select_get())


def _object_name(obj):
    return "" if obj is None else str(getattr(obj, "name", "") or "")


def _selected_objects(scene, selected_objects=None):
    if selected_objects is not None:
        return tuple(obj for obj in tuple(selected_objects or ()) if _is_selected(obj))
    return tuple(obj for obj in tuple(getattr(scene, "objects", ()) or ()) if _is_selected(obj))


def _selected_names(objects):
    seen, out = set(), []
    for obj in tuple(objects or ()):
        name = _object_name(obj)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def update_selection_order(scene, selected_objects=None, active_object=None):
    current = _selected_names(_selected_objects(scene, selected_objects))
    if not current:
        return _store_and_return(scene, [])
    ordered, active = _ordered_names(scene, current), _object_name(active_object)
    if len(current) == 1 and active in current:
        return _store_and_return(scene, [active])
    ordered += [n for n in current if n not in ordered and n != active]
    ordered += [active] if active in current and active not in ordered else []
    return _store_and_return(scene, ordered)


def _ordered_names(scene, current):
    selected = set(current)
    return [name for name in selection_order(scene) if name in selected]


def _store_and_return(scene, names):
    set_selection_order(scene, names)
    return list(names)


def ordered_selected_objects(scene, selected_objects=None, active_object=None):
    names = update_selection_order(scene, selected_objects, active_object)
    items = { _object_name(obj): obj for obj in _selected_objects(scene, selected_objects) }
    return tuple(items[name] for name in names if name in items)


def ordered_selected_objects_matching(scene, predicate, selected_objects=None, active_object=None):
    return tuple(obj for obj in ordered_selected_objects(scene, selected_objects, active_object) if predicate(obj))
