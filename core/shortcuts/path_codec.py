import bpy
import re

from ..scp_runtime.bound_objects import find_bound_entry_by_object
from ..selection import get_active_scp


_SPEC_RE = re.compile(r"^([A-Za-z_]\w*)(?:\[(\d+)\])?$")
_FULL_OBJECT_RE = re.compile(r"^bpy\.data\.objects\[(['\"])(.+?)\1\](.+)$")
_ACTIVE_KINDS = {"active_scp_prop", "active_scp_object"}
_FIXED_KINDS = {"scp_prop", "scp_object", "object_rna"}
_RAW_KIND = "object_rna"


def make_shortcut_path(kind, prop_spec, entity_id=""):
    parts = [f"af://{str(kind or '').strip()}"]
    parts += [str(entity_id or "").strip()] if entity_id else []
    parts.append(str(prop_spec or "").strip())
    return "/".join(parts)


def parse_prop_spec(raw):
    match = _SPEC_RE.match(str(raw or "").strip())
    if not match:
        return "", -1
    return match.group(1), -1 if match.group(2) is None else int(match.group(2))


def parse_shortcut_path(raw):
    text = str(raw or "").strip()
    if not text.startswith("af://"):
        return _raw_object_path(text)
    parts = text[5:].split("/", 2)
    if len(parts) == 2 and parts[0] in _ACTIVE_KINDS:
        return parts[0], "", parts[1]
    if len(parts) == 3 and parts[0] in (_FIXED_KINDS | {"scp_bound_rna"}):
        return parts[0], parts[1], parts[2]
    return "", "", ""


def _raw_object_path(text):
    obj, tail = _object_path_parts(text)
    return ("", "", "") if obj is None or not tail else (_RAW_KIND, obj.name, tail)


def split_bound_entity_id(entity_id):
    scp_id, _sep, bound_id = str(entity_id or "").partition("|")
    return str(scp_id or ""), str(bound_id or "")


def make_bound_entity_id(scp_id, bound_id):
    return f"{str(scp_id or '')}|{str(bound_id or '')}"


def _canonical_path(raw):
    kind, entity_id, prop_spec = parse_shortcut_path(raw)
    return "" if not kind else make_shortcut_path(kind, prop_spec, entity_id=entity_id)


def canonical_shortcut_path(raw):
    return _canonical_path(raw)


def _full_object_match(raw):
    return _FULL_OBJECT_RE.match(str(raw or "").strip())


def _normalize_tail(raw):
    text = str(raw or "").strip()
    return text[1:] if text.startswith(".") else text


def _object_path_parts(raw):
    match = _full_object_match(raw)
    if match is None:
        return None, ""
    return bpy.data.objects.get(match.group(2)), _normalize_tail(match.group(3))


def _valid_bound_tail(tail):
    return bool(str(tail or "").strip())


def _bound_shortcut(root, context, raw):
    scp = get_active_scp(root, context)
    obj, tail = _object_path_parts(raw)
    if scp is None or obj is None or not _valid_bound_tail(tail):
        return ""
    return str(raw or "").strip() if find_bound_entry_by_object(scp, obj) is not None else ""


def normalize_shortcut_path(root, context, raw):
    return _bound_shortcut(root, context, raw) or _canonical_path(raw)
