"""Attachment choices independent of the active viewport selection."""
from ...core.vcp.surface_reference import from_object, key, is_muscle, reference
from .scp import scp_label


def surface_choices(root, scene):
    if root is None: return []
    targets = {key(from_object(obj)) for obj in scene.objects if obj.type == 'MESH' and obj.get('af_root_name') == root.name}
    ordered = sorted(filter(None, targets), key=lambda value: _order(root, value))
    return [(value, scp_label(root, value), 'Use this published attachment surface') for value in ordered]


def _order(root, value):
    ref = reference(value)
    return (not is_muscle(value), ref.entity_id, ref.instance != 'source', ref.surface.value != 'MUSCLE_INFL', scp_label(root, value))
