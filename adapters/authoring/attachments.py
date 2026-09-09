"""Resolve detached native attachment records without exposing RNA."""
from ...core.authoring.errors import require
from ...core.vcp.attachment_backend import resolve_attachment_world


def resolve_rows(root, scene, fiber):
    values, collections = fiber['values'], fiber['collections']
    if values['topology_mode'] == 'LOOP':
        rows = [r['values'] for r in collections['loop_anchors']]
    else:
        rows = [dict(parent_id=values['a_parent_id'], attach_param=values['a_attach_param'])]
        rows += [r['values'] for r in collections['mid_touches']]
        rows += [dict(parent_id=values['b_parent_id'], attach_param=values['b_attach_param'])]
    return [resolve(root, scene, row) for row in rows]


def resolve(root, scene, row):
    point = resolve_attachment_world(root, scene, row['parent_id'], row['attach_param'])
    require(point is not None, 'NATIVE_ATTACHMENT_UNRESOLVED')
    return dict(owner=row['parent_id'], point=list(point), offset=row.get('normal_offset', 0.))
