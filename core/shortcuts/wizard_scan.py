from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ShortcutWizardField:
    label: str = ""
    data_path: str = ""
    default_name: str = ""


def collect_shortcut_fields(obj):
    fields = []
    fields += _transform_fields(obj)
    fields += _modifier_fields(obj)
    fields += _custom_fields(obj, _object_base(obj))
    return tuple(fields)


def _transform_fields(obj):
    fields = []
    for name, prop_name in (("Location", "location"), ("Rotation", "rotation_euler"), ("Scale", "scale")):
        fields += _component_fields(_object_base(obj), prop_name, name, ("X", "Y", "Z"))
    return fields


def _modifier_fields(obj):
    fields = []
    for mod in tuple(getattr(obj, "modifiers", ()) or ()):
        fields += _owner_numeric_fields(_modifier_base(obj, mod), mod, f"{mod.name}: ")
        fields += _custom_fields(mod, _modifier_base(obj, mod), prefix=f"{mod.name}: ")
    return fields


def _owner_numeric_fields(base, owner, prefix=""):
    fields = []
    for prop in _sorted_numeric_props(owner):
        fields += _prop_fields(base, prefix, prop)
    return fields


def _sorted_numeric_props(owner):
    props = [prop for prop in _prop_defs(owner) if _is_numeric_prop(prop)]
    return tuple(sorted(props, key=lambda prop: str(getattr(prop, "name", "") or getattr(prop, "identifier", ""))))


def _prop_defs(owner):
    props = getattr(getattr(owner, "rna_type", None), "properties", ())
    return tuple(props.values()) if hasattr(props, "values") else tuple(props or ())


def _is_numeric_prop(prop):
    length = int(getattr(prop, "array_length", 0) or 0)
    kind = str(getattr(prop, "type", "") or "").upper()
    return kind in {"INT", "FLOAT"} and not _skip_prop(prop) and length <= 4


def _skip_prop(prop):
    flags = (bool(getattr(prop, "is_readonly", False)), bool(getattr(prop, "is_hidden", False)))
    ident = str(getattr(prop, "identifier", "") or "")
    return any(flags) or ident in {"name", "rna_type"} or ident.startswith("bl_")


def _prop_fields(base, prefix, prop):
    return _array_prop_fields(base, prefix, prop) if _array_prop(prop) else _scalar_prop_fields(base, prefix, prop)


def _array_prop(prop):
    return int(getattr(prop, "array_length", 0) or 0) > 1


def _scalar_prop_fields(base, prefix, prop):
    label = f"{prefix}{_prop_label(prop)}"
    return [ShortcutWizardField(label=label, data_path=_prop_path(base, _prop_id(prop)), default_name=_default_name(_prop_label(prop)))]


def _array_prop_fields(base, prefix, prop):
    suffixes = _component_suffixes(int(getattr(prop, "array_length", 0) or 0), getattr(prop, "subtype", ""))
    return _component_fields(base, _prop_id(prop), f"{prefix}{_prop_label(prop)}", suffixes)


def _component_fields(base, prop_name, label, suffixes):
    return [ShortcutWizardField(label=f"{label} {suffix}", data_path=_prop_path(base, prop_name, index), default_name=_default_name(f"{_base_label(label)} {suffix}")) for index, suffix in enumerate(tuple(suffixes or ()))]


def _component_suffixes(length, subtype):
    if length == 3 and _axis_subtype(subtype):
        return ("X", "Y", "Z")
    if length == 4 and str(subtype or "").upper() == "QUATERNION":
        return ("W", "X", "Y", "Z")
    return tuple(str(index) for index in range(length)) if 1 < length <= 4 else ()


def _axis_subtype(subtype):
    return str(subtype or "").upper() in {"XYZ", "TRANSLATION", "EULER", "VELOCITY", "ACCELERATION", "DIRECTION"}


def _prop_label(prop):
    return str(getattr(prop, "name", "") or getattr(prop, "identifier", "")).strip()


def _prop_id(prop):
    return str(getattr(prop, "identifier", "") or "")


def _default_name(label):
    return f"* {str(label or '').strip()}".strip()


def _base_label(label):
    return str(label or "").split(": ", 1)[-1].strip()


def _custom_fields(owner, base, prefix=""):
    fields = []
    for label, key, value in _custom_items(owner):
        fields += _custom_value_fields(base, prefix, label, key, value, _custom_subtype(owner, key))
    return fields


def _custom_items(owner):
    labels = _custom_label_map(owner)
    rows = [_custom_item(owner, key, labels) for key in _owner_keys(owner)]
    rows = [row for row in rows if row is not None]
    return tuple(sorted(rows, key=lambda row: str(row[0] or "").lower()))


def _custom_item(owner, key, labels):
    if not _show_custom_key(owner, key, labels):
        return None
    return labels.get(str(key or ""), str(key or "")), key, _owner_value(owner, key)


def _owner_keys(owner):
    try:
        return tuple(owner.keys()) if hasattr(owner, "keys") else tuple()
    except TypeError:
        return tuple()


def _owner_value(owner, key):
    try:
        return owner.get(key)
    except Exception:
        return None


def _is_visible_custom_key(key):
    text = str(key or "")
    return bool(text) and text != "_RNA_UI" and not text.startswith("_")


def _show_custom_key(owner, key, labels):
    return _is_visible_custom_key(key) and not _hide_custom_key(owner, key, labels)


def _hide_custom_key(owner, key, labels):
    text = str(key or "")
    return _is_geometry_nodes_modifier(owner) and (_gn_attribute_key(text) or _gn_unknown_socket(text, labels))


def _custom_value_fields(base, prefix, label, key, value, subtype):
    return _custom_array_fields(base, prefix, label, key, value, subtype) if _custom_array(value) else _custom_scalar_fields(base, prefix, label, key, value)


def _custom_scalar_fields(base, prefix, label, key, value):
    text = f"{prefix}{label}"
    return [] if not _is_numeric_scalar(value) else [ShortcutWizardField(label=text, data_path=_custom_path(base, key), default_name=_default_name(label))]


def _custom_array_fields(base, prefix, label, key, value, subtype):
    if not _is_numeric_array(value):
        return []
    suffixes = _component_suffixes(len(tuple(value or ())), subtype)
    return _custom_component_fields(base, prefix, label, key, suffixes)


def _custom_component_fields(base, prefix, label, key, suffixes):
    text = f"{prefix}{label}"
    return [ShortcutWizardField(label=f"{text} {suffix}", data_path=_custom_path(base, key, index), default_name=_default_name(f"{label} {suffix}")) for index, suffix in enumerate(tuple(suffixes or ()))]


def _custom_array(value):
    return hasattr(value, "__len__") and not _is_scalar_like(value)


def _is_numeric_scalar(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_numeric_array(value):
    data = tuple(value or ())
    return bool(data) and len(data) <= 4 and all(_is_numeric_scalar(item) for item in data)


def _is_scalar_like(value):
    return isinstance(value, (str, bytes)) or _is_numeric_scalar(value) or isinstance(value, bool)


def _custom_subtype(owner, key):
    try:
        return owner.id_properties_ui(key).as_dict().get("subtype", "")
    except Exception:
        return ""


def _custom_label_map(owner):
    return _gn_input_label_map(owner) if _is_geometry_nodes_modifier(owner) else {}


def _is_geometry_nodes_modifier(owner):
    return str(getattr(owner, "type", "") or "").upper() == "NODES"


def _gn_input_label_map(owner):
    items = _gn_interface_items(owner)
    return {str(getattr(item, "identifier", "") or ""): _gn_item_label(item) for item in items if _gn_input_socket(item)}


def _gn_interface_items(owner):
    group = getattr(owner, "node_group", None)
    iface = getattr(group, "interface", None)
    return tuple(getattr(iface, "items_tree", ()) or ())


def _gn_input_socket(item):
    kind = str(getattr(item, "item_type", "") or "").upper()
    return kind == "SOCKET" and str(getattr(item, "in_out", "") or "").upper() == "INPUT"


def _gn_item_label(item):
    return str(getattr(item, "name", "") or getattr(item, "identifier", "") or "").strip()


def _gn_attribute_key(text):
    return text.endswith("_use_attribute") or text.endswith("_attribute_name")


def _gn_unknown_socket(text, labels):
    return text.startswith("Socket_") and text not in labels


def _object_base(obj):
    return f"bpy.data.objects[{_quoted(getattr(obj, 'name', ''))}]"


def _modifier_base(obj, mod):
    return f'{_object_base(obj)}.modifiers[{_quoted(getattr(mod, "name", ""))}]'


def _prop_path(base, prop_name, index=None):
    text = f"{base}.{prop_name}"
    return text if index is None else f"{text}[{int(index)}]"


def _custom_path(base, key, index=None):
    text = f"{base}{_custom_spec(key)}"
    return text if index is None else f"{text}[{int(index)}]"


def _custom_spec(key):
    return f"[{_quoted(key)}]"


def _quoted(value):
    return json.dumps(str(value or ""))
