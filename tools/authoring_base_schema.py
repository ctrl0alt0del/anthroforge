"""Explicit heads, preserved outer boundaries and shared seam identities."""
try:
    from tools.authoring_schema_v04 import S, I, B, N, enum, obj, array, operation
except ModuleNotFoundError:
    from authoring_schema_v04 import S, I, B, N, enum, obj, array, operation


def base_operation():
    heads = array(obj(dict(id=S, label=S)), 1, 32)
    arc = obj(dict(id=S, vertex_ids=array(I, 2, 2048), role=enum('origin', 'insertion', 'side', 'seam', 'cleft', 'crop'),
                   segments=dict(type='integer', minimum=1, maximum=64)), ['id', 'vertex_ids', 'role'])
    border = array(obj(dict(arc=S, reverse=B), ['arc']), 3, 32)
    patch = obj(dict(id=S, head_ids=array(S, 1, 32), source_triangles=array(I, 1, 50000), boundary=border))
    settings = obj(dict(rings=dict(type='integer', minimum=2, maximum=6), iterations=dict(type='integer', minimum=0, maximum=16),
                        regularization=dict(type='number', exclusiveMinimum=0, maximum=100)), [])
    fields = dict(expected_scene_revision=S, source_object=S, topology_digest=S, geometry_digest=S,
                  heads=heads, arcs=array(arc, 3, 256), patches=array(patch, 1, 32))
    return operation('anatomy.prepare_base', dict(**fields, settings=settings), list(fields))
