import bpy
from dataclasses import dataclass
import re

from ..selection import get_active_scp, get_active_scp_object
from ..scp_runtime.common import find_bound_scp_obj_by_id, find_geometry_scp_obj, find_scp_by_id
from .path_codec import parse_prop_spec, parse_shortcut_path, split_bound_entity_id


_CUSTOM_PROP_RE = re.compile(r'^\[([\'"])(.+?)\1\](?:\[(\d+)\])?$')


@dataclass(frozen=True)
class ShortcutTarget:
    owner: object = None
    prop_name: str = ""
    index: int = -1
    value_type: str = ""
    array_length: int = 0
    enum_items: tuple = ()
    error: str = ""


def _invalid(error):
    return ShortcutTarget(error=str(error or "Invalid shortcut."))


def _owner_for_kind(root, context, kind, entity_id):
    if kind == "active_scp_prop":
        return get_active_scp(root, context)
    if kind == "active_scp_object":
        return get_active_scp_object(root, context)
    if kind == "object_rna":
        return bpy.data.objects.get(entity_id)
    if kind == "scp_prop":
        return find_scp_by_id(root, entity_id)
    if kind == "scp_object":
        return find_geometry_scp_obj(context.scene, root.name, entity_id)
    return _bound_owner(root, context, kind, entity_id)


def _bound_owner(root, context, kind, entity_id):
    if kind != "scp_bound_rna":
        return None
    scp_id, bound_id = split_bound_entity_id(entity_id)
    return find_bound_scp_obj_by_id(context.scene, root.name, scp_id, bound_id)


def _split_owner_prop(prop_spec):
    text = str(prop_spec or "")
    if text.startswith("["):
        return "", text
    bracket = text.rfind('["')
    bracket = max(bracket, text.rfind("['"))
    if bracket > 0 and bracket > text.rfind("."):
        return text[:bracket], text[bracket:]
    return tuple(text.rsplit(".", 1)) if "." in text else ("", text)


def _resolved_owner(owner, owner_path):
    if owner is None or not owner_path:
        return owner
    try:
        return owner.path_resolve(owner_path)
    except Exception:
        return None


def _prop_rna(owner, prop_name):
    props = None if owner is None else getattr(getattr(owner, "rna_type", None), "properties", None)
    return None if props is None else props.get(prop_name)


def _custom_prop_parts(prop_name):
    match = _CUSTOM_PROP_RE.match(str(prop_name or "").strip())
    if match is None:
        return "", -1
    key = f'["{match.group(2)}"]'
    index = -1 if match.group(3) is None else int(match.group(3))
    return key, index


def _custom_prop_value(owner, prop_name):
    key, _index = _custom_prop_parts(prop_name)
    return None if owner is None or not key else owner.get(key[2:-2])


def _custom_index_error(value, index):
    sized = hasattr(value, "__len__") and not isinstance(value, (str, bytes))
    if index < 0:
        return ""
    if not sized:
        return "Property is not an array."
    return "" if index < len(value) else "Array index is out of range."


def _custom_target(owner, prop_name):
    value = _custom_prop_value(owner, prop_name)
    if value is None:
        return _invalid("Property was not found on the bound target.")
    key, index = _custom_prop_parts(prop_name)
    return ShortcutTarget(owner=owner, prop_name=key, index=index, value_type=_custom_value_type(value), array_length=_custom_array_length(value), error=_custom_index_error(value, index))


def _missing_owner_error(kind):
    return "Select an SCP to resolve this shortcut." if kind.startswith("active_") else "The bound shortcut target was not found."


def _index_error(prop_rna, index):
    if index < 0:
        return ""
    if int(getattr(prop_rna, "array_length", 0)) <= 0:
        return "Property is not an array."
    return "" if index < int(prop_rna.array_length) else "Array index is out of range."


def _resolve_prop(kind, owner, prop_spec):
    final_owner, leaf = _owner_and_leaf(owner, prop_spec)
    if final_owner is None:
        return _invalid(_missing_owner_error(kind))
    if _custom_prop_parts(leaf)[0]:
        return _custom_target(final_owner, leaf)
    prop_name, index = parse_prop_spec(leaf)
    prop_rna = _prop_rna(final_owner, prop_name)
    if prop_rna is None:
        return _invalid("Property was not found on the bound target.")
    if getattr(prop_rna, "type", "") in {"POINTER", "COLLECTION"}:
        return _invalid("Only direct value properties are supported.")
    return ShortcutTarget(owner=final_owner, prop_name=prop_name, index=index, value_type=_rna_value_type(prop_rna), array_length=int(getattr(prop_rna, "array_length", 0) or 0), enum_items=_enum_items(prop_rna), error=_index_error(prop_rna, index))


def _owner_and_leaf(owner, prop_spec):
    owner_path, leaf = _split_owner_prop(prop_spec)
    return _resolved_owner(owner, owner_path), str(leaf or "")


def _custom_value_type(value):
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, str):
        return "STRING"
    return _custom_value_type((list(value or [0.0]) or [0.0])[0])


def _custom_array_length(value):
    sized = hasattr(value, "__len__") and not isinstance(value, (str, bytes))
    return len(value) if sized else 0


def _rna_value_type(prop_rna):
    kinds = {"BOOLEAN": "BOOL", "INT": "INT", "FLOAT": "FLOAT", "STRING": "STRING", "ENUM": "ENUM"}
    return kinds.get(str(getattr(prop_rna, "type", "") or "").upper(), "")


def _enum_items(prop_rna):
    items = getattr(prop_rna, "enum_items", ()) or ()
    return tuple((str(item.identifier), str(item.name), str(item.description)) for item in items)


def resolve_shortcut(root, context, raw):
    kind, entity_id, prop_spec = parse_shortcut_path(raw)
    if not kind:
        return _invalid("Unsupported data path.")
    target = _resolve_prop(kind, _owner_for_kind(root, context, kind, entity_id), prop_spec)
    return _invalid(target.error) if target.error else target
