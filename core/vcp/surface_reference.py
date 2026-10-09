"""Typed attachment identities; plain legacy keys continue to denote SCPs.

The canonical key is the persisted parent_id/target_id transport, not a Blender
object name. Domain consumers use reference() and never interpret its encoding.
"""
import json
from dataclasses import replace
from .surface_target import SurfaceTargetRef, SurfaceTargetKind, target_ref, target_payload, target_from_payload

PREFIX = 'AFSURFACE:'


def reference(value):
    if isinstance(value, SurfaceTargetRef): return value
    if isinstance(value, dict): return _input_reference(value)
    raw = str(value or '')
    if raw.startswith(PREFIX): return target_from_payload(json.loads(raw[len(PREFIX):]))
    return target_ref('SCP', raw, 'SCP_GEOMETRY') if raw else target_ref()


def _input_reference(value):
    defaults = {'MUSCLE': 'MUSCLE_INFL', 'SCP': 'SCP_GEOMETRY'}
    return target_from_payload(dict(surface=defaults.get(value.get('type'), 'AUTO'), **value) if 'surface' not in value else value)


def key(value):
    ref = reference(value)
    if ref.kind == SurfaceTargetKind.NONE: return ''
    if ref.kind == SurfaceTargetKind.SCP and ref.instance == 'source': return ref.entity_id
    return PREFIX + json.dumps(target_payload(ref), sort_keys=True, separators=(',', ':'))


def is_muscle(value):
    if isinstance(value, str) and not value.startswith(PREFIX): return False
    return reference(value).kind == SurfaceTargetKind.MUSCLE


def from_object(obj):
    if obj is None or obj.type != 'MESH': return target_ref()
    if obj.get('af_muscle_proxy'):
        role = str(obj.get('af_muscle_surface', 'INFL'))
        return target_ref('MUSCLE', obj.get('af_source_muscle_id') or obj.get('af_muscle_id', ''),
                          'MUSCLE_' + role, 'mirror' if obj.get('af_muscle_mirror_proxy') else 'source')
    if obj.get('af_scp_geometry'): return _scp_object_reference(obj)
    return target_ref()


def _scp_object_reference(obj):
    if obj.get('af_scp_mirror'):
        return target_ref('SCP', obj.get('af_source_scp_id') or obj.get('af_scp_id', ''), 'SCP_GEOMETRY', 'mirror')
    return reference(obj.get('af_scp_id', ''))


def is_typed(value):
    return not isinstance(value, str) or value.startswith(PREFIX)


def dependency(value, root=None):
    ref = reference(value)
    entity = ref.entity_id
    if root is not None and ref.kind == SurfaceTargetKind.SCP and entity.startswith('AFI_'):
        from ..scp_runtime.common import attachment_dependency_id
        entity = attachment_dependency_id(root, entity)
    return ref.kind.value, entity


def remap(value, scps=None, muscles=None):
    ref = reference(value); mapping = muscles if ref.kind == SurfaceTargetKind.MUSCLE else scps
    return key(replace(ref, entity_id=dict(mapping or {}).get(ref.entity_id, ref.entity_id)))


def opposite(value):
    ref = reference(value)
    return key(replace(ref, instance='mirror' if ref.instance == 'source' else 'source'))


def remap_binding(raw, scps=None, muscles=None):
    try: value = json.loads(raw)
    except (ValueError, TypeError): return raw
    if not isinstance(value, dict) or 'target' not in value: return raw
    value['target'] = target_payload(reference(remap(value['target'], scps, muscles)))
    return json.dumps(value, sort_keys=True, separators=(',', ':'))
