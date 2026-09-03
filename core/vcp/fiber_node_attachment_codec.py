"""Persistent array payload for ordinary SCP-to-Fiber node attachments."""

import json
from dataclasses import dataclass, replace
from math import isfinite


NODE_ATTACHMENT_VERSION = 1


@dataclass(frozen=True)
class FiberNodeAttachment:
    target_id: str
    attach_raw: str
    offset_local: tuple


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
    values = () if payload is None else (row.target_id for row in payload.nodes)
    return tuple(dict.fromkeys(value for value in values if value))


def remap_node_attachment_targets(raw, mapping):
    payload = decode_node_attachments(raw)
    values = {str(key): str(value) for key, value in dict(mapping or {}).items() if str(value)}
    if payload is None or any(row.target_id not in values for row in payload.nodes):
        return ""
    nodes = tuple(replace(row, target_id=values[row.target_id]) for row in payload.nodes)
    return encode_node_attachments(replace(payload, nodes=nodes))


def _node_dict(node):
    return {"target_id": node.target_id, "attach_raw": node.attach_raw,
            "offset_local": list(node.offset_local)}


def _decode_payload(value):
    if not isinstance(value, dict) or int(value.get("version", 0)) != NODE_ATTACHMENT_VERSION:
        return None
    nodes = tuple(_decode_node(row) for row in value.get("nodes", ()))
    return _decoded_payload(value, nodes) if all(nodes) else None


def _decoded_payload(value, nodes):
    count = int(value.get("point_count", 0))
    if count < 2 or count != len(nodes):
        return None
    return FiberNodeAttachmentPayload(NODE_ATTACHMENT_VERSION, count,
                                      bool(value.get("cyclic", False)), nodes)


def _decode_node(value):
    if not isinstance(value, dict):
        return None
    offset = tuple(float(item) for item in value.get("offset_local", ()))
    valid = len(offset) == 3 and all(isfinite(item) for item in offset)
    target, raw = str(value.get("target_id", "") or ""), str(value.get("attach_raw", "") or "")
    return FiberNodeAttachment(target, raw, offset) if valid and target and raw else None
