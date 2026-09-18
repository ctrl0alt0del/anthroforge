"""AI-supplied heads and boundary arcs constrain experimental underside patch fitting."""
from collections import defaultdict
import numpy as np
from . import base_patch as B
from .errors import require


def validate_mesh(definition):
    vertices = np.asarray(definition['vertices'], dtype=float); faces = np.asarray(definition['triangles'], dtype=int)
    require(np.array_equal(faces, np.asarray(definition['triangles'])), 'BASE_INVALID_TRIANGLE_TYPE')
    require(vertices.ndim == 2 and vertices.shape[1] == 3 and np.isfinite(vertices).all(), 'BASE_INVALID_VERTICES')
    require(faces.ndim == 2 and faces.shape[1] == 3 and len(faces) > 0, 'BASE_INVALID_TRIANGLES')
    require(int(faces.min()) >= 0 and int(faces.max()) < len(vertices), 'BASE_INVALID_VERTEX_INDEX')
    heads = [h['id'] for h in definition['heads']]; require(len(heads) == len(set(heads)) and heads, 'BASE_INVALID_HEADS')
    ids = [p['id'] for p in definition['patches']]; require(len(ids) == len(set(ids)) and ids, 'BASE_INVALID_PATCHES')
    for patch in definition['patches']:
        require(bool(patch['head_ids']) and set(patch['head_ids']) <= set(heads), 'BASE_UNKNOWN_HEAD')
        chosen = patch['source_triangles']; require(chosen and min(chosen) >= 0 and max(chosen) < len(faces), 'BASE_INVALID_SOURCE_SELECTION')
    require(set(heads) == {h for p in definition['patches'] for h in p['head_ids']}, 'BASE_UNUSED_HEAD')
    return vertices, faces


def sample_arc(vertices, arc):
    ids = np.asarray(arc['vertex_ids'], dtype=int); count = arc.get('segments', 12)
    require(len(ids) >= 2 and ids.min() >= 0 and ids.max() < len(vertices), 'BASE_INVALID_ARC')
    require(type(count) is int and 1 <= count <= 64, 'BASE_INVALID_SAMPLING')
    points = vertices[ids]; lengths = np.linalg.norm(np.diff(points, axis=0), axis=1); times = np.r_[0., np.cumsum(lengths)]
    require(np.all(lengths > 1e-12), 'BASE_DEGENERATE_ARC')
    t = np.linspace(0, times[-1], count+1); samples = np.column_stack([np.interp(t, times, points[:, axis]) for axis in range(3)])
    keys = [('vertex', int(ids[0]))]+[('arc', arc['id'], i) for i in range(1, count)]+[('vertex', int(ids[-1]))]
    return dict(points=samples, keys=keys, role=arc['role'])


def boundary(patch, arcs):
    pieces, keys = [], []
    for item in patch['boundary']:
        require(item['arc'] in arcs, 'BASE_UNKNOWN_ARC'); arc = arcs[item['arc']]; reverse = item.get('reverse', False)
        pieces.append(arc['points'][::-1] if reverse else arc['points']); keys.append(arc['keys'][::-1] if reverse else arc['keys'])
    require(all(keys[i][-1] == keys[(i+1) % len(keys)][0] for i in range(len(keys))), 'BASE_OPEN_PERIMETER')
    points, identities = np.concatenate([p[:-1] for p in pieces]), [k for part in keys for k in part[:-1]]
    require(3 <= len(points) <= 192 and len(identities) == len(set(identities)), 'BASE_PINCHED_PERIMETER')
    return points, identities


def connections(definition):
    uses = defaultdict(list); arcs = {arc['id']: arc for arc in definition['arcs']}
    require(len(arcs) == len(definition['arcs']), 'BASE_DUPLICATE_ARC')
    for patch in definition['patches']:
        for item in patch['boundary']:
            require(item['arc'] in arcs, 'BASE_UNKNOWN_ARC'); uses[item['arc']].append((patch['id'], item.get('reverse', False)))
    for identity, arc in arcs.items():
        rows = uses[identity]; seam = arc['role'] == 'seam'
        require(len(rows) == (2 if seam else 1), 'BASE_INVALID_ARC_USE', 'Only an explicitly shared seam may join patches.')
        require(not seam or rows[0][1] != rows[1][1], 'BASE_SEAM_ORIENTATION')
    return [dict(arc=k, patches=[r[0] for r in rows]) for k, rows in uses.items() if len(rows) == 2]


def orientation(result, vertices, faces):
    source = vertices[faces]; target = result['vertices'][result['triangles']]; ids, _distance = B.correspondence(target.mean(1), source.mean(1))
    normals = np.cross(source[:, 1]-source[:, 0], source[:, 2]-source[:, 0]); generated = np.cross(target[:, 1]-target[:, 0], target[:, 2]-target[:, 0])
    area = np.linalg.norm(generated, axis=1); dots = np.einsum('ij,ij->i', generated, normals[ids]); sign = 1 if np.sum(area[dots >= 0]) >= np.sum(area[dots < 0]) else -1
    return dict(opposed_area_fraction=float(area[dots*sign < 0].sum()/max(area.sum(), 1e-20)),
                near_zero_triangles=int((area <= max(area.max(), 1e-20)*1e-10).sum()))


def make_patch(patch, arcs, vertices, faces, settings):
    points, keys = boundary(patch, arcs); selected = faces[patch['source_triangles']]
    result = B.fit_boundary(vertices, selected, points, settings); result['boundary_keys'] = keys
    result['id'], result['head_ids'] = patch['id'], list(patch['head_ids'])
    result['quality'] = dict(topology=B.topology(result['triangles']), orientation=orientation(result, vertices, selected))
    return result


def weld(patches):
    vertices, faces, identities = [], [], {}
    for patch in patches:
        boundary_keys = dict(zip(patch['boundary'], patch['boundary_keys'])); mapped = []
        for index, point in enumerate(patch['vertices']):
            key = boundary_keys.get(index, ('interior', patch['id'], index))
            if key not in identities:
                identities[key] = len(vertices); vertices.append(point)
            require(np.linalg.norm(np.asarray(vertices[identities[key]])-point) < 1e-10, 'BASE_SEAM_MISMATCH')
            mapped.append(identities[key])
        faces.extend(np.asarray(mapped)[patch['triangles']])
    return np.asarray(vertices), np.asarray(faces)


def prepare(definition):
    vertices, faces = validate_mesh(definition); joins = connections(definition)
    arcs = {arc['id']: sample_arc(vertices, arc) for arc in definition['arcs']}; settings = definition.get('settings', {})
    require(2 <= settings.get('rings', 5) <= 6 and 0 <= settings.get('iterations', 8) <= 16, 'BASE_INVALID_BUDGET')
    require(0 < settings.get('regularization', .4) <= 100, 'BASE_INVALID_REGULARIZATION')
    patches = [make_patch(p, arcs, vertices, faces, settings) for p in definition['patches']]
    assembled_vertices, assembled_faces = weld(patches); report = B.topology(assembled_faces)
    ready = all(p['quality']['orientation']['opposed_area_fraction'] <= .001 and not p['quality']['orientation']['near_zero_triangles'] for p in patches)
    ready &= report['euler'] == report['connected_components'] == report['boundary_components'] == 1 and report['nonmanifold_edges'] == report['pinched_boundary_vertices'] == 0
    return dict(version='muscle_base.experimental.v1', status='geometry_candidate' if ready else 'unresolved', heads=definition['heads'],
                patches=patches, connections=joins, vertices=assembled_vertices, triangles=assembled_faces, topology=report,
                limitations=['Anatomical correspondence, 3D self-intersections and native curve feasibility require separate checks.'])
