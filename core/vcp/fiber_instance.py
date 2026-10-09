"""An evaluated instance adapts one authored Fiber without duplicating its graph."""
import json
from types import SimpleNamespace
from dataclasses import replace
from .surface_reference import opposite, reference
from .surface_target import target_payload
from .fiber_node_attachment_codec import decode_node_attachments, encode_node_attachments
from .shared_point_storage import slots, point_record


def mirrored_binding(raw):
    value = json.loads(raw)
    if 'target' in value: value['target'] = target_payload(reference(opposite(value['target'])))
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def mirrored_point(point):
    return SimpleNamespace(id=point.id, point_id=point.id, parent_id=opposite(point.parent_id),
        attach_param=mirrored_binding(point.attach_param), normal_offset=-point.normal_offset)


def mirrored_payload(raw):
    payload = decode_node_attachments(raw)
    if payload is None: raise ValueError('Source instance bindings are unavailable.')
    return encode_node_attachments(replace(payload, nodes=tuple(_node(row) for row in payload.nodes)))


def _node(row):
    x, y, z = row.offset_local
    values = dict(target_id=opposite(row.target_id), attach_raw=mirrored_binding(row.attach_raw), offset_local=(x, y, -z))
    if hasattr(row, 'influences'): values['influences'] = tuple(_node(item) for item in row.influences)
    return replace(row, **values)


class MirroredFiber:
    def __init__(self, source, routing=False):
        self.source = source
        self.id = source.id + ('@mirror' if routing else '')
        points = [point_record(owner, slot) for owner, slot, _role in slots(source)]
        if any(point is None for point in points): raise ValueError('A shared source binding is missing.')
        self.attachment_records = tuple(mirrored_point(point) for point in points)
        self.loop_anchors = self.attachment_records if source.topology_mode == 'LOOP' else ()
        self.mid_touches = self.attachment_records[1:-1] if source.topology_mode == 'OPEN' else ()
        self.attachment_supports = tuple(SimpleNamespace(target_id=opposite(row.target_id)) for row in source.attachment_supports)
        self.node_attachments_json = _retained_payload(source)
        self.a_parent_id, self.b_parent_id = (self.attachment_records[i].parent_id for i in (0, -1))
        self.a_attach_param, self.b_attach_param = (self.attachment_records[i].attach_param for i in (0, -1))
        self.free_path_json = _free_payload(source, self.node_attachments_json)

    def __getattr__(self, name):
        return getattr(self.source, name)

    def get(self, key, default=None):
        return self.source.get('af_mirror_' + key, self.source.get(key, default))

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.source['af_mirror_' + key] = value

    def pop(self, key, default=None):
        return self.source.pop('af_mirror_' + key, default)

    def __contains__(self, key):
        return 'af_mirror_' + key in self.source or key in self.source


def _free_payload(source, raw):
    from .free_path import is_free, decode, encode, pair_digest
    if not is_free(source): return source.free_path_json
    payload = decode(source.free_path_json)
    payload['attachment_digest'] = pair_digest(payload, raw)
    return encode(payload)


def lookup(fibers, identity):
    source = next((f for f in fibers if f.id == identity.removesuffix('@mirror')), None)
    return MirroredFiber(source, True) if source is not None and identity.endswith('@mirror') else source


def _retained_payload(source):
    from .free_path import digest
    stamp = digest(source.node_attachments_json)
    if source.get('af_mirror_binding_source') == stamp and source.get('af_mirror_node_bindings'):
        return source['af_mirror_node_bindings']
    return mirrored_payload(source.node_attachments_json)


def retain_payload(source, raw):
    from .free_path import digest
    source['af_mirror_node_bindings'] = raw
    source['af_mirror_binding_source'] = digest(source.node_attachments_json)
