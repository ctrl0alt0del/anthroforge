"""Validate retained tissue bindings without treating tessellation as connectivity."""
import json
from dataclasses import replace

from ..vcp.attachment_backend import surface_binding_topology
from ..vcp.surface_binding_codec import decode_binding_envelope, require_matching_envelope
from ..vcp.surface_target import target_payload


def target_envelope(target, raw, runtime, rest_signature=""):
    envelope = decode_binding_envelope(raw, target.reference, target.topology_signature)
    if _compatible_legacy(envelope, target, runtime):
        envelope = replace(envelope, topology_signature=target.topology_signature)
    require_matching_envelope(envelope, target.reference, target.topology_signature, rest_signature)
    return envelope


def _compatible_legacy(envelope, target, runtime):
    stored = envelope.topology_signature
    if not stored or stored.startswith('connectivity-v1:'):
        return False
    if envelope.bindings and all(_sealed_connectivity(row, target) for row in envelope.bindings):
        return True
    return stored == surface_binding_topology(target.mesh_object, runtime)


def _sealed_connectivity(row, target):
    try:
        value = json.loads(row.get('raw', '') if isinstance(row, dict) else row)
    except (ValueError, TypeError):
        return False
    return (isinstance(value, dict) and value.get('target') == target_payload(target.reference)
            and value.get('topology_signature') == target.topology_signature)


def require_stored_topology(target, stored, raw, runtime):
    if stored == target.topology_signature:
        return
    envelope = decode_binding_envelope(raw, target.reference, stored)
    if stored and envelope.topology_signature == stored and _compatible_legacy(envelope, target, runtime):
        target_envelope(target, raw, runtime)
        return
    raise ValueError('Attachment target topology changed. Use Rebind.')


def promote_binding_topology(raw, signature):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(value, dict) or int(value.get('version', 0)) < 3:
        return raw
    if value.get('topology_signature') == signature:
        return raw
    value['topology_signature'] = signature
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def commit_binding_topology(tissue, signature):
    if not signature:
        return
    for field in ('control_bindings_json', 'base_bindings_json'):
        setattr(tissue, field, promote_binding_topology(getattr(tissue, field), signature))
    for row in tissue.attachments:
        row.bindings_json = promote_binding_topology(row.bindings_json, signature)
