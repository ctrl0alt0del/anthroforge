from dataclasses import dataclass

from ..selection import get_active_scp, get_active_scp_object
from ..scp_runtime.common import find_scp_by_id, find_source_scp_obj
from .path_codec import parse_prop_spec, parse_shortcut_path


@dataclass(frozen=True)
class ShortcutTarget:
    owner: object = None
    prop_name: str = ""
    index: int = -1
    error: str = ""


def _invalid(error):
    return ShortcutTarget(error=str(error or "Invalid shortcut."))


def _owner_for_kind(root, context, kind, entity_id):
    if kind == "active_scp_prop":
        return get_active_scp(root, context)
    if kind == "active_scp_object":
        return get_active_scp_object(root, context)
    if kind == "scp_prop":
        return find_scp_by_id(root, entity_id)
    if kind == "scp_object":
        return find_source_scp_obj(context.scene, root.name, entity_id)
    return None


def _prop_rna(owner, prop_name):
    props = None if owner is None else getattr(getattr(owner, "rna_type", None), "properties", None)
    return None if props is None else props.get(prop_name)


def _missing_owner_error(kind):
    if kind.startswith("active_"):
        return "Select an SCP to resolve this shortcut."
    return "The bound SCP target was not found."


def _index_error(prop_rna, index):
    if index < 0:
        return ""
    if int(getattr(prop_rna, "array_length", 0)) <= 0:
        return "Property is not an array."
    return "" if index < int(prop_rna.array_length) else "Array index is out of range."


def _resolve_prop(kind, owner, prop_spec):
    prop_name, index = parse_prop_spec(prop_spec)
    prop_rna = _prop_rna(owner, prop_name)
    if owner is None:
        return _invalid(_missing_owner_error(kind))
    if prop_rna is None:
        return _invalid("Property was not found on the bound target.")
    if getattr(prop_rna, "type", "") in {"POINTER", "COLLECTION"}:
        return _invalid("Only direct value properties are supported.")
    return ShortcutTarget(owner=owner, prop_name=prop_name, index=index, error=_index_error(prop_rna, index))


def resolve_shortcut(root, context, raw):
    kind, entity_id, prop_spec = parse_shortcut_path(raw)
    if not kind:
        return _invalid("Unsupported data path.")
    target = _resolve_prop(kind, _owner_for_kind(root, context, kind, entity_id), prop_spec)
    return _invalid(target.error) if target.error else target
