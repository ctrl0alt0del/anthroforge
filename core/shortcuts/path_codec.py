import re

from ..selection import get_active_scp, get_active_scp_object
from ..scp_runtime.common import find_source_scp_obj


_SPEC_RE = re.compile(r"^([A-Za-z_]\w*)(?:\[(\d+)\])?$")
_SCP_RE = re.compile(r"^(?:.*\.)?af_scp_system\.scps\[\d+\]\.([A-Za-z_]\w*(?:\[\d+\])?)$")
_ACTIVE_KINDS = {"active_scp_prop", "active_scp_object"}
_FIXED_KINDS = {"scp_prop", "scp_object"}


def make_shortcut_path(kind, prop_spec, entity_id=""):
    parts = [f"af://{str(kind or '').strip()}"]
    if entity_id:
        parts.append(str(entity_id or "").strip())
    parts.append(str(prop_spec or "").strip())
    return "/".join(parts)


def parse_prop_spec(raw):
    match = _SPEC_RE.match(str(raw or "").strip())
    if not match:
        return "", -1
    index = -1 if match.group(2) is None else int(match.group(2))
    return match.group(1), index


def _path_parts(text):
    parts = text[5:].split("/")
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def parse_shortcut_path(raw):
    text = str(raw or "").strip()
    if not text.startswith("af://"):
        return "", "", ""
    kind, entity_id, prop_spec = _path_parts(text)
    prop_name, _index = parse_prop_spec(prop_spec)
    if not prop_name:
        return "", "", ""
    if kind in _ACTIVE_KINDS and not entity_id:
        return kind, "", prop_spec
    if kind in _FIXED_KINDS and entity_id:
        return kind, entity_id, prop_spec
    return "", "", ""


def _owner_has_prop(owner, prop_spec):
    prop_name, _index = parse_prop_spec(prop_spec)
    props = None if owner is None else getattr(getattr(owner, "rna_type", None), "properties", None)
    return bool(prop_name and props and props.get(prop_name) is not None)


def _canonical_path(raw):
    kind, entity_id, prop_spec = parse_shortcut_path(raw)
    if not kind:
        return ""
    return make_shortcut_path(kind, prop_spec, entity_id=entity_id)


def _fixed_scp_prop(root, context, prop_spec):
    scp = get_active_scp(root, context)
    if scp is None or not _owner_has_prop(scp, prop_spec):
        return ""
    return make_shortcut_path("scp_prop", prop_spec, entity_id=scp.id)


def _fixed_scp_object(root, context, prop_spec):
    obj = get_active_scp_object(root, context)
    scp_id = "" if obj is None else str(obj.get("af_scp_id") or "")
    owner = find_source_scp_obj(context.scene, root.name, scp_id)
    if not scp_id or not _owner_has_prop(owner, prop_spec):
        return ""
    return make_shortcut_path("scp_object", prop_spec, entity_id=scp_id)


def _active_to_fixed(root, context, kind, prop_spec):
    if kind == "active_scp_prop":
        return _fixed_scp_prop(root, context, prop_spec)
    if kind == "active_scp_object":
        return _fixed_scp_object(root, context, prop_spec)
    return ""


def _scp_prop_path(root, context, raw):
    match = _SCP_RE.match(str(raw or "").strip())
    if not match:
        return ""
    return _fixed_scp_prop(root, context, match.group(1))


def _simple_prop_path(root, context, raw):
    prop_spec = str(raw or "").strip()
    if not parse_prop_spec(prop_spec)[0]:
        return ""
    return _fixed_scp_prop(root, context, prop_spec) or _fixed_scp_object(root, context, prop_spec)


def normalize_shortcut_path(root, context, raw):
    kind, _entity_id, prop_spec = parse_shortcut_path(raw)
    if kind:
        return _active_to_fixed(root, context, kind, prop_spec) or _canonical_path(raw)
    for fn in (_scp_prop_path, _simple_prop_path):
        fixed = fn(root, context, raw)
        if fixed:
            return fixed
    return ""
