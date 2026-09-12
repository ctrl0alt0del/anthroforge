"""Persistent array payload for ordinary SCP-to-Fiber node attachments."""

import json
from dataclasses import dataclass, replace
from math import isfinite


NODE_ATTACHMENT_VERSION = 2


@dataclass(frozen=True)
class FiberNodeInfluence:
    target_id: str
    attach_raw: str
    offset_local: tuple
    weight: float


@dataclass(frozen=True)
class FiberNodeAttachment:
    target_id: str
    attach_raw: str
    offset_local: tuple
    influences: tuple = ()


@dataclass(frozen=True)
class FiberNodeAttachmentPayload:
    version: int
    point_count: int
    cyclic: bool
    nodes: tuple


def encode_node_attachments(payload):
    value = {"version": payload.version, "point_count": payload.point_count,
             "cyclic": payload.cyclic, "nodes": [_node_dict(row) for row in payload.nodes]}
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_node_attachments(raw):
    try:
        return _decode_payload(json.loads(str(raw or "")))
    except Exception:
        return None


def node_attachment_target_ids(fiber):
    raw = getattr(fiber, "node_attachments_json", "")
    return node_attachment_target_ids_from_raw(raw)


def node_attachment_target_ids_from_raw(raw):
    payload = decode_node_attachments(raw)
    values = () if payload is None else (item.target_id for row in payload.nodes for item in node_influences(row))
    return tuple(dict.fromkeys(value for value in values if value))


def remap_node_attachment_targets(raw, mapping):
    payload = decode_node_attachments(raw)
    values = {str(key): str(value) for key, value in dict(mapping or {}).items() if str(value)}
    if payload is None or any(sid not in values for sid in _payload_targets(payload)):
        return ""
    nodes = tuple(_remap_node(row, values) for row in payload.nodes)
    return encode_node_attachments(replace(payload, nodes=nodes))


def _node_dict(node):
    value = {"target_id": node.target_id, "attach_raw": node.attach_raw,
             "offset_local": list(node.offset_local)}
    if getattr(node, "influences", ()):
        value["influences"] = [dict(_node_dict(row), weight=row.weight) for row in node.influences]
    return value


def _decode_payload(value):
    if not isinstance(value, dict) or int(value.get("version", 0)) not in (1, NODE_ATTACHMENT_VERSION):
        return None
    nodes = tuple(_decode_node(row) for row in value.get("nodes", ()))
    return _decoded_payload(value, nodes) if all(nodes) else None


def _decoded_payload(value, nodes):
    count = int(value.get("point_count", 0))
    if count < 2 or count != len(nodes):
        return None
    if int(value['version']) == 1 and any(row.influences for row in nodes): return None
    return FiberNodeAttachmentPayload(int(value['version']), count,
                                      bool(value.get("cyclic", False)), nodes)


def _decode_node(value):
    if not isinstance(value, dict):
        return None
    offset = tuple(float(item) for item in value.get("offset_local", ()))
    valid = len(offset) == 3 and all(isfinite(item) for item in offset)
    target, raw = str(value.get("target_id", "") or ""), str(value.get("attach_raw", "") or "")
    influences = _decode_influences(value.get("influences", ()))
    return FiberNodeAttachment(target, raw, offset, influences) if valid and target and raw and influences is not None else None


def node_influences(node):
    return node.influences or (FiberNodeInfluence(node.target_id, node.attach_raw, node.offset_local, 1.0),)


def _decode_influences(values):
    if not isinstance(values, (tuple, list)) or len(values) > 2: return None
    rows = tuple(_decode_influence(value) for value in values)
    if not all(rows): return None
    if rows and abs(sum(row.weight for row in rows) - 1.0) > 1e-9: return None
    if len({row.target_id for row in rows}) != len(rows): return None
    return rows


def _decode_influence(value):
    if not isinstance(value, dict) or 'influences' in value: return None
    row = _decode_node(value); weight = float(value.get('weight', 0))
    if row is None or not isfinite(weight) or not 0 < weight <= 1: return None
    return FiberNodeInfluence(row.target_id, row.attach_raw, row.offset_local, weight)


def _payload_targets(payload):
    return {row.target_id for row in payload.nodes} | {item.target_id for row in payload.nodes for item in node_influences(row)}


def _remap_node(row, mapping):
    influences = tuple(replace(item, target_id=mapping[item.target_id]) for item in row.influences)
    return replace(row, target_id=mapping[row.target_id], influences=influences)
