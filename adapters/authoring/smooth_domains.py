"""Retained-body cuts and explicitly qualified shared-junction offsets."""
import numpy as np
from mathutils import Vector
from ...core.authoring.errors import require
from ...core.vcp.muscle_domain_clip import clip_domain


def world_plane(root, domain):
    if domain['mode'] == 'full': return None
    origin = root.matrix_world @ Vector(domain['origin'])
    normal = root.matrix_world.to_3x3().inverted().transposed() @ Vector(domain['normal'])
    return dict(normal=list(normal), offset=normal.dot(origin), keep_positive=domain['keep_positive'])


def clipped(vertices, triangles, plane):
    if plane is None: return dict(vertices=np.asarray(vertices), triangles=np.asarray(triangles))
    result = clip_domain(vertices, vertices, triangles, plane)
    require(len(result.faces) > 0, 'BASE_EMPTY_OUTPUT_DOMAIN')
    return dict(vertices=result.base_vertices, triangles=result.faces)


def prepare(root, parts):
    for part in parts:
        plane = world_plane(root, part['output_domain']); part['world_plane'] = plane
        for key in ('native', 'base'):
            part['retained_'+key] = clipped(part[key]['vertices'], part[key]['triangles'], plane)


def junction(root, scene, hit, offset, purpose):
    from ...core.vcp.fiber_pin_snapping import qualify_attachment
    binding = hit['attachment']; result = qualify_attachment(root, scene, binding['parent_id'], binding['attach_param'], offset=offset)
    require(result.valid and result.raw == binding['attach_param'], 'BASE_JUNCTION_UNQUALIFIED')
    return dict(hit, point=list(result.point), normal_offset=offset, purpose=purpose, kind='shared_structural_junction')
