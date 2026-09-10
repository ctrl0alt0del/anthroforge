"""Persist patch boundaries as weights on vertex indices, independent of face ordering."""
from collections import defaultdict
from .codec import digest
from .errors import require


def canonical(face):
    row = tuple(face)
    return min(row[index:]+row[:index] for index in range(len(row)))


def topology(geometry):
    if 'polygons' in geometry:
        from .polygon_patches import topology as polygon_topology
        return polygon_topology(geometry)
    return triangle_topology(geometry)


def triangle_topology(geometry):
    return 'vertices-v1:'+digest([len(geometry['vertices']), sorted(canonical(t) for t in geometry['triangles'])])


def face_map(geometry):
    result = defaultdict(list)
    for index, face in enumerate(geometry['triangles']):
        result[canonical(face)].append(index)
    return result


def bind(geometry, patches):
    if 'polygons' in geometry:
        from .polygon_patches import bind as bind_polygons
        return bind_polygons(geometry, patches)
    faces, occurrences = geometry['triangles'], face_map(geometry)
    rows = [dict(tri_vidx=list(faces[r['triangle']]), polygon=r['polygon'], occurrence=occurrences[canonical(faces[r['triangle']])].index(r['triangle'])) for r in patches]
    return dict(kind='surface_patch', topology_digest=topology(geometry), patches=rows)


def resolve(geometry, query):
    if query['topology_digest'].startswith('vertices-v2:'):
        from .polygon_patches import resolve as resolve_polygons
        return resolve_polygons(geometry, query)
    if not query['topology_digest'].startswith('vertices-v1:'):
        from .visual_mesh import topology as legacy_topology
        require(legacy_topology(geometry) == query['topology_digest'], 'SURFACE_PATCH_REBIND_REQUIRED')
        return query['patches']
    require(triangle_topology(geometry) == query['topology_digest'], 'SURFACE_PATCH_REBIND_REQUIRED')
    faces, mapping = geometry['triangles'], face_map(geometry)
    return [resolve_row(row, faces, mapping) for row in query['patches']]


def resolve_row(row, faces, mapping):
    require('tri_vidx' in row, 'SURFACE_PATCH_INVALID')
    saved = row['tri_vidx']
    candidates, occurrence = mapping.get(canonical(saved), []), row.get('occurrence', 0)
    require(0 <= occurrence < len(candidates), 'SURFACE_PATCH_REBIND_REQUIRED')
    index = candidates[occurrence]
    columns = [saved.index(v) for v in faces[index]]
    return dict(triangle=index, polygon=[[weights[c] for c in columns] for weights in row['polygon']])
