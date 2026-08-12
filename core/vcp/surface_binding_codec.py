import hashlib
import json

from .surface_target import SurfaceBindingEnvelope, SurfaceTargetKind, target_from_payload, target_payload


def encode_binding_envelope(target, topology_signature, bindings, rest_topology_signature=""):
    payload = {"version": 3, "target": target_payload(target),
               "topology_signature": str(topology_signature or ""), "bindings": list(bindings)}
    if rest_topology_signature:
        payload["rest_topology_signature"] = str(rest_topology_signature)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def decode_binding_envelope(raw, legacy_target=None, legacy_topology=""):
    value = _json_value(raw)
    if isinstance(value, dict) and int(value.get("version", 0)) >= 3:
        return _version_three(value)
    rows = value.get("bindings", ()) if isinstance(value, dict) else value
    return SurfaceBindingEnvelope(legacy_target or target_from_payload({}), str(legacy_topology or ""),
                                  tuple(rows or ()), version=_legacy_version(value))


def require_matching_envelope(envelope, target, topology_signature, rest_signature=""):
    if envelope.target != target:
        raise ValueError("Binding target identity does not match the assigned target. Use Rebind.")
    if envelope.topology_signature != str(topology_signature or ""):
        raise ValueError("Attachment target topology changed. Use Rebind.")
    if rest_signature and envelope.rest_topology_signature != str(rest_signature):
        raise ValueError("Soft Tissue rest topology changed. Use Rebind.")


def rest_topology_signature(vertex_count, faces):
    payload = {"vertex_count": int(vertex_count), "faces": [list(map(int, face)) for face in faces]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def remap_binding_target(raw, target_type, source_id, target_id):
    value = _json_value(raw)
    if not isinstance(value, dict) or int(value.get("version", 0)) < 3:
        return raw
    target = dict(value.get("target") or {})
    if str(target.get("type", "")) != str(target_type) or str(target.get("id", "")) != str(source_id):
        return raw
    target["id"], value["target"] = str(target_id), target
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _version_three(value):
    return SurfaceBindingEnvelope(target_from_payload(value.get("target")),
                                  str(value.get("topology_signature", "") or ""),
                                  tuple(value.get("bindings", ()) or ()),
                                  str(value.get("rest_topology_signature", "") or ""), 3)


def _legacy_version(value):
    return int(value.get("version", 1)) if isinstance(value, dict) else 1


def _json_value(raw):
    try:
        return json.loads(str(raw or "[]"))
    except Exception:
        return []
